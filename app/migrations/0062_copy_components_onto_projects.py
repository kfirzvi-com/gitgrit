"""Projects take over from components (phase 1b: copy the data).

The copy, per project:
* stack memberships of any of its components -> the project's;
* the root component's kind and technologies -> the project's;
* every non-root component -> a *suggested project* (with the stacks it was
  in, so adding it restores its memberships);
* component edges -> project edges (both ends mapped to their projects;
  edges inside one repository collapse away until its projects are added);
* externals and infrastructure -> their component's project.

Zero downtime: the previous release keeps serving while the new one rolls
out. It deletes projects, stacks and workspaces with Django's Python cascade,
which doesn't know the tables 0061 added, so those tables cascade deletes in
the database too.
"""
from django.db import migrations

# The previous release deletes projects, stacks and workspaces with Django's
# Python cascade, which doesn't know the tables added here; the database
# cascades into them instead, so its deletes don't trip their foreign keys.
NEW_TABLE_FOREIGN_KEYS = """
    (conrelid::regclass::text IN ('project_stacks', 'project_dependencies'))
    OR (conrelid::regclass::text IN ('external_dependencies', 'infrastructure_components')
        AND confrelid::regclass::text = 'projects')
"""
CASCADE_IN_DATABASE = f"""
DO $$
DECLARE c record;
BEGIN
    FOR c IN
        SELECT conname, conrelid::regclass AS tbl, pg_get_constraintdef(oid) AS def
        FROM pg_constraint WHERE contype = 'f' AND ({NEW_TABLE_FOREIGN_KEYS})
    LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', c.tbl, c.conname);
        EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s', c.tbl, c.conname,
                       replace(c.def, 'DEFERRABLE', 'ON DELETE CASCADE DEFERRABLE'));
    END LOOP;
END $$;
"""
CASCADE_IN_PYTHON_ONLY = CASCADE_IN_DATABASE.replace(
    "replace(c.def, 'DEFERRABLE', 'ON DELETE CASCADE DEFERRABLE')",
    "replace(c.def, 'ON DELETE CASCADE ', '')",
)

def copy_components(apps, schema_editor):
    Project = apps.get_model("app", "Project")
    Component = apps.get_model("app", "Component")
    ComponentStack = apps.get_model("app", "ComponentStack")
    ComponentDependency = apps.get_model("app", "ComponentDependency")
    ProjectStack = apps.get_model("app", "ProjectStack")
    ProjectDependency = apps.get_model("app", "ProjectDependency")
    ExternalDependency = apps.get_model("app", "ExternalDependency")
    InfrastructureComponent = apps.get_model("app", "InfrastructureComponent")

    stacks_of: dict = {}
    for component_id, stack_id in ComponentStack.objects.values_list("component_id", "stack_id"):
        stacks_of.setdefault(component_id, []).append(str(stack_id))

    memberships = set()
    for project in Project.objects.all():
        components = list(Component.objects.filter(project=project).order_by("path"))
        suggestions = []
        for c in components:
            for stack_id in stacks_of.get(c.pk, ()):
                memberships.add((project.pk, stack_id))
            if c.path == "":
                project.kind = c.kind
                project.technologies = list(c.technologies or [])
            else:
                suggestions.append(
                    {
                        "path": c.path,
                        "name": c.name,
                        "kind": c.kind,
                        "description": c.description,
                        "technologies": list(c.technologies or []),
                        "stack_ids": stacks_of.get(c.pk, []),
                    }
                )
        project.suggested_projects = suggestions
        project.save(update_fields=["kind", "technologies", "suggested_projects"])
    ProjectStack.objects.bulk_create(
        [ProjectStack(project_id=p, stack_id=s) for p, s in memberships], ignore_conflicts=True
    )

    project_of = dict(Component.objects.values_list("pk", "project_id"))
    edges = {}
    for d in ComponentDependency.objects.all():
        source, target = project_of.get(d.source_id), project_of.get(d.target_id)
        if source and target and source != target and (source, target) not in edges:
            edges[(source, target)] = ProjectDependency(
                tenant_id=d.tenant_id, source_id=source, target_id=target,
                label=d.label, description=d.description,
            )
    ProjectDependency.objects.bulk_create(edges.values(), ignore_conflicts=True)

    for model in (ExternalDependency, InfrastructureComponent):
        for row in model.objects.filter(project__isnull=True).only("pk", "component_id"):
            row.project_id = project_of.get(row.component_id)
            row.save(update_fields=["project"])




class Migration(migrations.Migration):
    dependencies = [
        ("app", "0061_projects_replace_components"),
    ]

    operations = [
        migrations.RunSQL(CASCADE_IN_DATABASE, CASCADE_IN_PYTHON_ONLY),
        migrations.RunPython(copy_components, migrations.RunPython.noop),
    ]
