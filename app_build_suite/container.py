from dependency_injector import containers, providers

from app_build_suite.build_steps.helm import (
    HelmChartToolLinter,
    HelmBuilderValidator,
    HelmGitVersionSetter,
    HelmChartBuilder,
)


class Container(containers.DeclarativeContainer):
    config = providers.Configuration()

    validator = providers.Selector(
        config.build_engine, helm3=providers.Singleton(HelmBuilderValidator)
    )

    version_setter = providers.Selector(
        config.build_engine, helm3=providers.Singleton(HelmGitVersionSetter)
    )

    ct_validator = providers.Singleton(HelmChartToolLinter)

    builder = providers.Selector(
        config.build_engine, helm3=providers.Singleton(HelmChartBuilder)
    )
