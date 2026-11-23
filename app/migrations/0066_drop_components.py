"""Projects take over from components (phase 2: drop the component tables).

Ships in the release after phase 1 (0060–0064), once no running code reads
the component tables. Database only: Django's model state already lost the
components in 0063.

1. Copy again what the previous release wrote to the component tables while
   it served next to phase 1: stack memberships, edges, and externals or
   infrastructure that know only their component. (Kind, technologies and
   suggestions are not touched: the new release owns them by now.)
2. Dedupe externals per project, name and direction, and infrastructure
   per project and name, then enforce both in the database, with the
   project now required.
3. Drop the component columns and tables.

Reversible in schema only: going back recreates the component tables and
columns empty (the phase-1 release never reads them) and lifts the
constraints, so earlier migrations can run back too.
"""
from django.db import migrations

# Foreign keys are deferred; checking them as rows change leaves no pending
# trigger events, which Postgres requires before the ALTER TABLEs below.
RECOPY = """
SET CONSTRAINTS ALL IMMEDIATE;

INSERT INTO project_stacks (id, project_id, stack_id, created_at)
SELECT gen_random_uuid(), c.project_id, cs.stack_id, now()
FROM component_stacks cs
JOIN components c ON c.id = cs.component_id
JOIN projects p ON p.id = c.project_id
JOIN stacks s ON s.id = cs.stack_id
ON CONFLICT (project_id, stack_id) DO NOTHING;

INSERT INTO project_dependencies (id, tenant_id, source_id, target_id, label, description, created_at, updated_at)
SELECT gen_random_uuid(), d.tenant_id, src.project_id, tgt.project_id, d.label, d.description, now(), now()
FROM component_dependencies d
JOIN components src ON src.id = d.source_id
JOIN components tgt ON tgt.id = d.target_id
WHERE src.project_id <> tgt.project_id
  AND EXISTS (SELECT 1 FROM projects WHERE id = src.project_id)
  AND EXISTS (SELECT 1 FROM projects WHERE id = tgt.project_id)
ON CONFLICT (source_id, target_id) DO NOTHING;

UPDATE external_dependencies e SET project_id = c.project_id
FROM components c
WHERE e.project_id IS NULL AND e.component_id = c.id
  AND EXISTS (SELECT 1 FROM projects WHERE id = c.project_id);
UPDATE infrastructure_components i SET project_id = c.project_id
FROM components c
WHERE i.project_id IS NULL AND i.component_id = c.id
  AND EXISTS (SELECT 1 FROM projects WHERE id = c.project_id);
DELETE FROM external_dependencies WHERE project_id IS NULL;
DELETE FROM infrastructure_components WHERE project_id IS NULL;
"""

DEDUPE_AND_ENFORCE = """
DELETE FROM external_dependencies e USING (
    SELECT id, row_number() OVER (
        PARTITION BY project_id, name, direction ORDER BY created_at, id
    ) AS n FROM external_dependencies
) ranked
WHERE e.id = ranked.id AND ranked.n > 1;
DELETE FROM infrastructure_components i USING (
    SELECT id, row_number() OVER (PARTITION BY project_id, name ORDER BY created_at, id) AS n
    FROM infrastructure_components
) ranked
WHERE i.id = ranked.id AND ranked.n > 1;

ALTER TABLE external_dependencies ALTER COLUMN project_id SET NOT NULL;
ALTER TABLE infrastructure_components ALTER COLUMN project_id SET NOT NULL;
ALTER TABLE external_dependencies
    ADD CONSTRAINT unique_project_external_dependency UNIQUE (project_id, name, direction);
ALTER TABLE infrastructure_components
    ADD CONSTRAINT unique_project_infrastructure UNIQUE (project_id, name);
"""

DROP_COMPONENTS = """
ALTER TABLE external_dependencies DROP CONSTRAINT IF EXISTS unique_external_dependency;
ALTER TABLE infrastructure_components DROP CONSTRAINT IF EXISTS unique_infrastructure_component;
ALTER TABLE external_dependencies DROP COLUMN component_id;
ALTER TABLE infrastructure_components DROP COLUMN component_id;
DROP TABLE component_dependencies;
DROP TABLE component_stacks;
DROP TABLE components;
"""


RESTORE_COMPONENT_SCHEMA = """
CREATE TABLE components (
    id uuid PRIMARY KEY,
    path varchar(1024) NOT NULL,
    name varchar(255) NOT NULL,
    kind varchar(10) NOT NULL,
    description text NOT NULL,
    technologies jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    project_id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    CONSTRAINT unique_component_path UNIQUE (project_id, path)
);
CREATE INDEX components_project_id_2becb930 ON components (project_id);
CREATE INDEX components_tenant_id_c7918525 ON components (tenant_id);
CREATE TABLE component_stacks (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL,
    component_id uuid NOT NULL REFERENCES components (id) DEFERRABLE INITIALLY DEFERRED,
    stack_id uuid NOT NULL,
    CONSTRAINT unique_component_stack UNIQUE (component_id, stack_id)
);
CREATE INDEX component_stacks_component_id_ad3dcfd2 ON component_stacks (component_id);
CREATE INDEX component_stacks_stack_id_9158f0a2 ON component_stacks (stack_id);
CREATE TABLE component_dependencies (
    id uuid PRIMARY KEY,
    label varchar(255) NOT NULL,
    description text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    tenant_id uuid NOT NULL,
    source_id uuid NOT NULL REFERENCES components (id) DEFERRABLE INITIALLY DEFERRED,
    target_id uuid NOT NULL REFERENCES components (id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT unique_component_dependency UNIQUE (source_id, target_id),
    CONSTRAINT component_dependency_no_self_loop CHECK (NOT source_id = target_id)
);
CREATE INDEX component_dependencies_source_id_727f9b68 ON component_dependencies (source_id);
CREATE INDEX component_dependencies_target_id_9a78dda4 ON component_dependencies (target_id);
CREATE INDEX component_dependencies_tenant_id_0ddacca2 ON component_dependencies (tenant_id);
ALTER TABLE external_dependencies
    ADD COLUMN component_id uuid REFERENCES components (id) DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT unique_external_dependency UNIQUE (component_id, name, direction);
ALTER TABLE infrastructure_components
    ADD COLUMN component_id uuid REFERENCES components (id) DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT unique_infrastructure_component UNIQUE (component_id, name);
"""
LIFT_CONSTRAINTS = """
ALTER TABLE external_dependencies DROP CONSTRAINT unique_project_external_dependency;
ALTER TABLE infrastructure_components DROP CONSTRAINT unique_project_infrastructure;
ALTER TABLE external_dependencies ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE infrastructure_components ALTER COLUMN project_id DROP NOT NULL;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0065_workspace_pins"),
    ]

    operations = [
        migrations.RunSQL(RECOPY, migrations.RunSQL.noop),
        migrations.RunSQL(DEDUPE_AND_ENFORCE, LIFT_CONSTRAINTS),
        migrations.RunSQL(DROP_COMPONENTS, RESTORE_COMPONENT_SCHEMA),
    ]
