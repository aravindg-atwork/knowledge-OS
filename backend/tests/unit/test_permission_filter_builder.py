from app.vectorstore.qdrant_store import build_permission_filter


def test_filter_scopes_to_workspace_and_roles():
    query_filter = build_permission_filter("workspace-123", ["admin", "member"])

    conditions = {c.key: c for c in query_filter.must}
    assert conditions["workspace_id"].match.value == "workspace-123"
    assert set(conditions["allowed_roles"].match.any) == {"admin", "member"}


def test_filter_has_exactly_two_must_conditions():
    query_filter = build_permission_filter("ws-1", ["member"])
    assert len(query_filter.must) == 2


def test_different_workspaces_produce_different_filters():
    filter_a = build_permission_filter("ws-a", ["member"])
    filter_b = build_permission_filter("ws-b", ["member"])

    workspace_condition_a = next(c for c in filter_a.must if c.key == "workspace_id")
    workspace_condition_b = next(c for c in filter_b.must if c.key == "workspace_id")
    assert workspace_condition_a.match.value != workspace_condition_b.match.value
