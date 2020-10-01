import argparse
import logging
import os
import shutil
import subprocess  # nosec
from typing import List, Optional

import configargparse

from app_build_suite.build_steps import BuildStep
from app_build_suite.build_steps.build_step import (
    StepType,
    STEP_BUILD,
    ALL_STEPS,
    STEP_TEST_UNIT,
)
from app_build_suite.build_steps.errors import ValidationError, BuildError
from app_build_suite.utils.git import GitRepoVersionInfo

logger = logging.getLogger(__name__)

_chart_yaml_app_version_key = "appVersion"
_chart_yaml_chart_version_key = "version"
_chart_yaml = "Chart.yaml"
_values_yaml = "values.yaml"


class HelmGitVersionSetter(BuildStep):
    repo_info: Optional[GitRepoVersionInfo] = None

    @property
    def steps_provided(self) -> List[StepType]:
        return [STEP_BUILD]

    def initialize_config(self, config_parser: configargparse.ArgParser) -> None:
        config_parser.add_argument(
            "--replace-app-version-with-git",
            required=False,
            action="store_true",
            help=f"Should the {_chart_yaml_app_version_key}  in {_chart_yaml} be replaced by a tag and hash from git",
        )
        config_parser.add_argument(
            "--replace-chart-version-with-git",
            required=False,
            action="store_true",
            help=f"Should the {_chart_yaml_chart_version_key} in {_chart_yaml} be replaced by a tag and hash from git",
        )

    def pre_run(self, config: argparse.Namespace) -> None:
        self.repo_info = GitRepoVersionInfo(config.chart_dir)
        if not self.repo_info.is_git_repo:
            raise ValidationError(
                self.name, f"Can't find valid git repository in {config.chart_dir}"
            )

    def run(self, config: argparse.Namespace) -> None:
        """
        Gets the git-version, then replaces keys in Chart.yaml
        :param config: the config object
        :return: None
        """
        if self.repo_info is not None:
            git_version = self.repo_info.get_git_version
        else:
            raise ValidationError(
                self.name, f"Can't find valid git repository in {config.chart_dir}"
            )
        new_lines: List[str] = []
        changes_made = False
        chart_yaml_path = os.path.join(config.chart_dir, _chart_yaml)
        with open(chart_yaml_path, "r") as file:
            lines = file.readlines()
            for line in lines:
                fields = line.split(":")
                if (
                    config.replace_chart_version_with_git
                    and fields[0] == _chart_yaml_chart_version_key
                ) or (
                    config.replace_app_version_with_git
                    and fields[0] == _chart_yaml_app_version_key
                ):
                    logger.info(
                        f"Replacing '{fields[0]}' with git version '{git_version}' in {_chart_yaml}."
                    )
                    changes_made = True
                    new_lines.append(f"{fields[0]}: {git_version}\n")
                else:
                    new_lines.append(line)
        if changes_made:
            logger.debug(f"Saving backup of {_chart_yaml} in {_chart_yaml}.back")
            shutil.copy2(chart_yaml_path, chart_yaml_path + ".back")
            with open(chart_yaml_path, "w") as file:
                logger.info(f"Saving {_chart_yaml} with version set from git.")
                file.writelines(new_lines)

    def cleanup(self, config: argparse.Namespace) -> None:
        pass


class HelmBuilderValidator(BuildStep):
    """Very simple validator that checks of the folder looks like Helm chart at all.
    """

    @property
    def steps_provided(self) -> List[StepType]:
        return ALL_STEPS

    def initialize_config(self, config_parser: configargparse.ArgParser) -> None:
        config_parser.add_argument(
            "-c",
            "--chart-dir",
            required=False,
            default=".",
            help="Path to the Helm Chart to build. Default is local dir.",
        )

    def pre_run(self, config: argparse.Namespace) -> None:
        """Validates if basic chart files are present in the configured directory."""
        if os.path.exists(
            os.path.join(config.chart_dir, _chart_yaml)
        ) and os.path.exists(os.path.join(config.chart_dir, _values_yaml)):
            return
        raise ValidationError(
            self.name, f"Can't find '{_chart_yaml}' or '{_values_yaml}' files."
        )

    def run(self, config: argparse.Namespace) -> None:
        pass

    def cleanup(self, config: argparse.Namespace) -> None:
        pass


class HelmChartToolLinter(BuildStep):
    """
    Runs helm ct linter against the chart.
    """

    @property
    def steps_provided(self) -> List[StepType]:
        return [STEP_TEST_UNIT]

    _ct_bin = "ct"
    _min_ct_version = "3.1.0"
    _max_ct_version = "4.0.0"

    def initialize_config(self, config_parser: configargparse.ArgParser) -> None:
        config_parser.add_argument(
            "--ct-config",
            required=False,
            help="Path to optional 'ct' lint config file.",
        )
        config_parser.add_argument(
            "--ct-schema", required=False, help="Path to optional 'ct' schema file.",
        )

    def pre_run(self, config: argparse.Namespace) -> None:
        # verify if binary present
        self._assert_binary_present_in_path(self._ct_bin)
        # verify version
        run_res = subprocess.run(["ct", "version"], capture_output=True)  # nosec
        version_line = str(run_res.stdout.splitlines()[0], "utf-8")
        version = version_line.split(":")[1].strip()
        self._assert_version_in_range(
            self._ct_bin, version, self._min_ct_version, self._max_ct_version
        )
        # validate config options
        if config.ct_config is not None and not os.path.isfile(config.ct_config):
            raise ValidationError(
                self.name, f"Chart tool config file {config.ct_config} doesn't exist.",
            )
        if config.ct_schema is not None and not os.path.isfile(config.ct_schema):
            raise ValidationError(
                self.name, f"Chart tool schema file {config.ct_schema} doesn't exist.",
            )

    def run(self, config: argparse.Namespace) -> None:
        args = [
            "ct",
            "lint",
            "--validate-maintainers=false",
            f"--charts={config.chart_dir}",
        ]
        if config.ct_config is not None:
            args.append(f"--config={config.ct_config}")
        if config.ct_schema is not None:
            args.append(f"--chart-yaml-schema={config.ct_schema}")
        logger.info("Running chart tool linting")
        run_res = subprocess.run(  # nosec, input params checked above in pre_run
            args, capture_output=True
        )
        for line in run_res.stdout.splitlines():
            logger.info(str(line, "utf-8"))
        if run_res.returncode != 0:
            logger.error(
                f"{self._ct_bin} run failed with exit code {run_res.returncode}"
            )
            raise BuildError(self.name, "Linting failed")

    def cleanup(self, config: argparse.Namespace) -> None:
        pass


class HelmChartBuilder(BuildStep):
    _helm_bin = "helm"
    _min_helm_version = "3.2.0"
    _max_helm_version = "4.0.0"

    @property
    def steps_provided(self) -> List[StepType]:
        return [STEP_BUILD]

    def initialize_config(self, config_parser: configargparse.ArgParser) -> None:
        pass

    def pre_run(self, config: argparse.Namespace) -> None:
        self._assert_binary_present_in_path(self._helm_bin)
        run_res = subprocess.run(["helm", "version"], capture_output=True)  # nosec
        version_line = str(run_res.stdout.splitlines()[0], "utf-8")
        prefix = "version.BuildInfo"
        if version_line.startswith(prefix):
            version_line = version_line[len(prefix) :].strip("{}")
        else:
            raise ValidationError(
                self.name, f"Can't parse {self._helm_bin} version number."
            )
        version_entries = version_line.split(",")[0]
        version = version_entries.split(":")[1].strip('"')
        self._assert_version_in_range(
            self._helm_bin, version, self._min_helm_version, self._max_helm_version
        )

    def run(self, config: argparse.Namespace) -> None:
        args = [
            "helm",
            "package",
            config.chart_dir,
        ]
        logger.info("Building chart with 'helm package'")
        run_res = subprocess.run(  # nosec, input params checked above in pre_run
            args, capture_output=True
        )
        for line in run_res.stdout.splitlines():
            logger.info(str(line, "utf-8"))
        if run_res.returncode != 0:
            logger.error(
                f"{self._helm_bin} run failed with exit code {run_res.returncode}"
            )
            raise BuildError(self.name, "Chart build failed")

    def cleanup(self, config: argparse.Namespace) -> None:
        pass
