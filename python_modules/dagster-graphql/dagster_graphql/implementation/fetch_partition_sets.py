import yaml
from graphql.execution.base import ResolveInfo

import dagster._check as check
from dagster.core.host_representation import (
    ExternalPartitionSet,
    RepositoryHandle,
    RepositorySelector,
)
from dagster.core.storage.pipeline_run import RunsFilter
from dagster.core.storage.tags import PARTITION_NAME_TAG, PARTITION_SET_TAG, TagType, get_tag_type

from .utils import capture_error


@capture_error
def get_partition_sets_or_error(graphene_info, repository_selector, pipeline_name):
    from ..schema.partition_sets import GraphenePartitionSet, GraphenePartitionSets

    check.inst_param(graphene_info, "graphene_info", ResolveInfo)
    check.inst_param(repository_selector, "repository_selector", RepositorySelector)
    check.str_param(pipeline_name, "pipeline_name")
    location = graphene_info.context.get_repository_location(repository_selector.location_name)
    repository = location.get_repository(repository_selector.repository_name)
    partition_sets = [
        partition_set
        for partition_set in repository.get_external_partition_sets()
        if partition_set.pipeline_name == pipeline_name
    ]

    return GraphenePartitionSets(
        results=[
            GraphenePartitionSet(
                external_repository_handle=repository.handle,
                external_partition_set=partition_set,
            )
            for partition_set in sorted(
                partition_sets,
                key=lambda partition_set: (
                    partition_set.pipeline_name,
                    partition_set.mode,
                    partition_set.name,
                ),
            )
        ]
    )


@capture_error
def get_partition_set(graphene_info, repository_selector, partition_set_name):
    from ..schema.partition_sets import GraphenePartitionSet, GraphenePartitionSetNotFoundError

    check.inst_param(graphene_info, "graphene_info", ResolveInfo)
    check.inst_param(repository_selector, "repository_selector", RepositorySelector)
    check.str_param(partition_set_name, "partition_set_name")
    location = graphene_info.context.get_repository_location(repository_selector.location_name)
    repository = location.get_repository(repository_selector.repository_name)
    partition_sets = repository.get_external_partition_sets()
    for partition_set in partition_sets:
        if partition_set.name == partition_set_name:
            return GraphenePartitionSet(
                external_repository_handle=repository.handle,
                external_partition_set=partition_set,
            )

    return GraphenePartitionSetNotFoundError(partition_set_name)


@capture_error
def get_partition_by_name(graphene_info, repository_handle, partition_set, partition_name):
    from ..schema.partition_sets import GraphenePartition

    check.inst_param(graphene_info, "graphene_info", ResolveInfo)
    check.inst_param(repository_handle, "repository_handle", RepositoryHandle)
    check.inst_param(partition_set, "partition_set", ExternalPartitionSet)
    check.str_param(partition_name, "partition_name")
    return GraphenePartition(
        external_repository_handle=repository_handle,
        external_partition_set=partition_set,
        partition_name=partition_name,
    )


@capture_error
def get_partition_config(graphene_info, repository_handle, partition_set_name, partition_name):
    from ..schema.partition_sets import GraphenePartitionRunConfig

    check.inst_param(repository_handle, "repository_handle", RepositoryHandle)
    check.str_param(partition_set_name, "partition_set_name")
    check.str_param(partition_name, "partition_name")

    result = graphene_info.context.get_external_partition_config(
        repository_handle,
        partition_set_name,
        partition_name,
    )

    return GraphenePartitionRunConfig(
        yaml=yaml.safe_dump(result.run_config, default_flow_style=False)
    )


@capture_error
def get_partition_tags(graphene_info, repository_handle, partition_set_name, partition_name):
    from ..schema.partition_sets import GraphenePartitionTags
    from ..schema.tags import GraphenePipelineTag

    check.inst_param(repository_handle, "repository_handle", RepositoryHandle)
    check.str_param(partition_set_name, "partition_set_name")
    check.str_param(partition_name, "partition_name")

    result = graphene_info.context.get_external_partition_tags(
        repository_handle, partition_set_name, partition_name
    )

    return GraphenePartitionTags(
        results=[
            GraphenePipelineTag(key=key, value=value)
            for key, value in result.tags.items()
            if get_tag_type(key) != TagType.HIDDEN
        ]
    )


@capture_error
def get_partitions(
    graphene_info, repository_handle, partition_set, cursor=None, limit=None, reverse=False
):
    from ..schema.partition_sets import GraphenePartition, GraphenePartitions

    check.inst_param(repository_handle, "repository_handle", RepositoryHandle)
    check.inst_param(partition_set, "partition_set", ExternalPartitionSet)
    result = graphene_info.context.get_external_partition_names(
        repository_handle, partition_set.name
    )

    partition_names = _apply_cursor_limit_reverse(result.partition_names, cursor, limit, reverse)

    return GraphenePartitions(
        results=[
            GraphenePartition(
                external_partition_set=partition_set,
                external_repository_handle=repository_handle,
                partition_name=partition_name,
            )
            for partition_name in partition_names
        ]
    )


def _apply_cursor_limit_reverse(items, cursor, limit, reverse):
    start = 0
    end = len(items)
    index = 0

    if cursor:
        index = next((idx for (idx, item) in enumerate(items) if item == cursor), None)

        if reverse:
            end = index
        else:
            start = index + 1

    if limit:
        if reverse:
            start = end - limit
        else:
            end = start + limit

    return items[max(start, 0) : end]


@capture_error
def get_partition_set_partition_statuses(
    graphene_info, repository_handle, partition_set_name, job_name
):
    from ..schema.partition_sets import GraphenePartitionStatus, GraphenePartitionStatuses

    check.inst_param(repository_handle, "repository_handle", RepositoryHandle)
    check.str_param(partition_set_name, "partition_set_name")
    run_partition_data = graphene_info.context.instance.run_storage.get_run_partition_data(
        partition_set_name, job_name, repository_handle.get_external_origin().get_id()
    )
    return GraphenePartitionStatuses(
        results=[
            GraphenePartitionStatus(
                id=f"{partition_set_name}:{p.partition}",
                partitionName=p.partition,
                runStatus=p.status,
                runDuration=p.end_time - p.start_time if p.end_time and p.start_time else None,
            )
            for p in run_partition_data
        ]
    )


def get_partition_set_partition_runs(graphene_info, partition_set):
    from ..schema.partition_sets import GraphenePartitionRun
    from ..schema.pipelines.pipeline import GrapheneRun

    result = graphene_info.context.get_external_partition_names(
        partition_set.repository_handle, partition_set.name
    )
    run_records = graphene_info.context.instance.get_run_records(
        RunsFilter(tags={PARTITION_SET_TAG: partition_set.name})
    )

    by_partition = {}
    for record in run_records:
        partition_name = record.pipeline_run.tags.get(PARTITION_NAME_TAG)
        if not partition_name or partition_name in by_partition:
            # all_partition_set_runs is in descending order by creation time, we should ignore
            # runs for the same partition if we've already considered the partition
            continue
        by_partition[partition_name] = record

    return [
        GraphenePartitionRun(
            id=f"{partition_set.name}:{partition_name}",
            partitionName=partition_name,
            run=GrapheneRun(by_partition[partition_name])
            if partition_name in by_partition
            else None,
        )
        # for partition_name, run_record in by_partition.items()
        for partition_name in result.partition_names
    ]
