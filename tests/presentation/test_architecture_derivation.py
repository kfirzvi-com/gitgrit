import pytest
from model_bakery import baker

from app.presentation.architecture import latest_scores_by_project, workspace_graph


@pytest.mark.django_db
def test_workspace_graph_derives_stack_edges_from_project_deps():
    tenant = baker.make("app.Tenant")
    conn = baker.make("app.PlatformConnection", tenant=tenant)
    stack_x = baker.make("app.Stack", tenant=tenant, name="X")
    stack_y = baker.make("app.Stack", tenant=tenant, name="Y")
    a = baker.make("app.Project", tenant=tenant, platform_connection=conn)
    b = baker.make("app.Project", tenant=tenant, platform_connection=conn)
    baker.make("app.ProjectStack", project=a, stack=stack_x)
    baker.make("app.ProjectStack", project=b, stack=stack_y)
    baker.make("app.ProjectDependency", tenant=tenant, source=a, target=b, label="REST")

    graph = workspace_graph(tenant, latest_scores_by_project(tenant))
    deps = graph["dependencies"]

    assert len(deps) == 1
    assert deps[0]["source"] == str(stack_x.id)
    assert deps[0]["target"] == str(stack_y.id)
    assert deps[0]["label"] == "REST"


@pytest.mark.django_db
def test_same_stack_project_dep_yields_no_stack_edge():
    tenant = baker.make("app.Tenant")
    conn = baker.make("app.PlatformConnection", tenant=tenant)
    stack = baker.make("app.Stack", tenant=tenant, name="One")
    a = baker.make("app.Project", tenant=tenant, platform_connection=conn)
    b = baker.make("app.Project", tenant=tenant, platform_connection=conn)
    baker.make("app.ProjectStack", project=a, stack=stack)
    baker.make("app.ProjectStack", project=b, stack=stack)
    baker.make("app.ProjectDependency", tenant=tenant, source=a, target=b)

    graph = workspace_graph(tenant, latest_scores_by_project(tenant))
    assert graph["dependencies"] == []  # intra-stack dep is not a stack→stack edge


@pytest.mark.django_db
def test_stack_node_analyzing_flag():
    tenant = baker.make("app.Tenant")
    conn = baker.make("app.PlatformConnection", tenant=tenant)
    stack = baker.make("app.Stack", tenant=tenant, name="S")
    baker.make(
        "app.Project", tenant=tenant, platform_connection=conn,
        stacks=[stack], deps_status="running",
    )

    graph = workspace_graph(tenant, latest_scores_by_project(tenant))
    assert graph["stacks"][0]["analyzing"] is True
