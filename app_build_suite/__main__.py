"""Main module."""
import logging
import sys
from typing import List, NewType, Callable

import configargparse

from app_build_suite.build_steps import (
    BuildStep,
    Error,
)
from app_build_suite.build_steps.build_step import ALL_STEPS, STEP_ALL
from app_build_suite.build_steps.errors import ConfigError
from .container import Container

version = "0.0.1"
app_name = "app_build_suite"
logger = logging.getLogger(__name__)

BuildEngineType = NewType("BuildEngineType", str)
BUILD_ENGINE_HELM3 = BuildEngineType("helm3")
ALL_BUILD_ENGINES = [BUILD_ENGINE_HELM3]


def get_pipeline(container: Container) -> List[BuildStep]:
    return [
        container.validator(),
        container.version_setter(),
        container.ct_validator(),
        container.builder(),
    ]


def configure_global_options(config_parser: configargparse.ArgParser):
    config_parser.add_argument(
        "-d",
        "--debug",
        required=False,
        default=False,
        action="store_true",
        help="Enable debug messages.",
    )
    config_parser.add_argument(
        "--version", action="version", version=f"{app_name} v{version}"
    )
    config_parser.add_argument(
        "-b",
        "--build-engine",
        required=False,
        default="helm3",
        type=BuildEngineType,
        help="Select the build engine used for building your chart.",
    )
    config_parser.add_argument(
        "--steps",
        nargs="+",
        help=f"List of steps to execute. Defaults to 'all'. Available steps: {ALL_STEPS}",
        required=False,
        default=["all"],
    )


def get_global_config_parser() -> configargparse.ArgParser:
    config_parser = configargparse.ArgParser(
        prog=app_name,
        add_config_file_help=True,
        default_config_files=[".abs.yaml"],
        description="Build and test Giant Swarm App Platform app.",
        add_env_var_help=True,
        auto_env_var_prefix="ABS_",
    )
    configure_global_options(config_parser)
    return config_parser


def validate_config(config: configargparse.Namespace):
    # validate build engine
    if config.build_engine not in ALL_BUILD_ENGINES:
        raise ConfigError(
            "build_engine",
            f"Unknown build engine '{config.build_engine}'. Valid engines are: {ALL_BUILD_ENGINES}.",
        )
    # validate steps
    for step in config.steps:
        if step not in ALL_STEPS:
            raise ConfigError(
                "steps", f"Unknown step '{step}'. Valid steps are: {ALL_STEPS}."
            )


def get_config(steps: List[BuildStep]) -> configargparse.Namespace:
    # initialize config, setup arg parsers
    try:
        config_parser = get_global_config_parser()
        for step in steps:
            step.initialize_config(config_parser)
        config = config_parser.parse_args()
        validate_config(config)
    except ConfigError as e:
        logger.error(f"Error when checking config option '{e.config_option}': {e.msg}")
        sys.exit(1)

    logger.info("Starting build with the following options")
    logger.info(f"\n{config_parser.format_values()}")
    return config


def _iterate_steps(
    config: configargparse.Namespace,
    steps: List[BuildStep],
    stage: str,
    error_exit_code: int,
    step_function: Callable[[BuildStep], None],
) -> None:
    for step in steps:
        if STEP_ALL in config.steps or any(
            s in step.steps_provided for s in config.steps
        ):
            logger.info(f"Running {stage} step for {step.name}")
            try:
                step_function(step)
            except Error as e:
                logger.error(
                    f"Error when running {stage} step for {step.name}: {e.msg}"
                )
                sys.exit(error_exit_code)
        else:
            logger.info(
                f"Skipping {stage} step for {step.name} as it was not configured to run."
            )


def run_pre_steps(config: configargparse.Namespace, steps: List[BuildStep]) -> None:
    _iterate_steps(config, steps, "pre-run", 2, lambda step: step.pre_run(config))


def run_build_steps(config: configargparse.Namespace, steps: List[BuildStep]) -> None:
    _iterate_steps(config, steps, "build", 3, lambda step: step.run(config))


def run_cleanup(config: configargparse.Namespace, steps: List[BuildStep]) -> None:
    _iterate_steps(config, steps, "cleanup", 4, lambda step: step.cleanup(config))


def main():
    log_format = "%(asctime)s %(name)s %(levelname)s: %(message)s"
    logging.basicConfig(format=log_format)
    logging.getLogger().setLevel(logging.INFO)

    container = Container()
    container.config.from_dict({"build_engine": "helm3"},)
    steps = get_pipeline(container)
    config = get_config(steps)

    if config.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    run_pre_steps(config, steps)
    run_build_steps(config, steps)
    run_cleanup(config, steps)


if __name__ == "__main__":
    main()
