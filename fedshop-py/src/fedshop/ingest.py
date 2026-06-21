from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import BenchmarkConfig


def run_isql(
    statement: str,
    isql_path: str,
    container_name: str | None = None,
    *,
    capture_output: bool = False,
) -> str | None:
    """Execute an isql statement, optionally inside a Docker container.

    This is the single subprocess boundary for all Virtuoso interactions.
    """
    quoted_isql = f'"{isql_path}"' if not isql_path.startswith('"') else isql_path
    escaped = statement.replace("'", "'\\''")
    cmd = f"{quoted_isql} 'EXEC={escaped}'"
    if container_name:
        cmd = f"docker exec {container_name} {quoted_isql} 'EXEC={escaped}'"

    proc = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if capture_output:
        return proc.stdout.decode("utf-8")
    return None


def grant_permissions(container_name: str | None, isql_path: str) -> None:
    run_isql('grant select on "DB.DBA.SPARQL_SINV_2" to "SPARQL";', isql_path, container_name)
    run_isql('grant execute on "DB.DBA.SPARQL_SINV_IMP" to "SPARQL";', isql_path, container_name)


def load_nq_file(
    nq_file: Path,
    graph_uri: str,
    isql_path: str,
    container_name: str | None,
    container_data_path: str,
) -> None:
    """Bulk-load a single .nq file into Virtuoso under the given graph URI."""
    filename = nq_file.name
    run_isql(f"ld_dir('{container_data_path}', '{filename}', '{graph_uri}');", isql_path, container_name)
    run_isql("rdf_loader_run(log_enable=>2);", isql_path, container_name)
    run_isql("checkpoint;", isql_path, container_name)


def register_sparql_endpoint(
    member_iri: str,
    lpath: str,
    isql_path: str,
    container_name: str | None,
    vport: int = 8890,
    vhost: str = "*ini*",
) -> str:
    """Register a named-graph SPARQL endpoint in Virtuoso.

    Returns the endpoint URL that was registered.
    """
    resolved_vhost = "localhost" if vhost == "*ini*" else vhost
    resolved_port = str(vport)
    lhost = f":{vport}"

    # Remove any existing virtual host entry for this path
    run_isql(
        f"DB.DBA.VHOST_REMOVE(vhost=>'{vhost}', lhost=>'{lhost}', lpath=>'{lpath}');",
        isql_path,
        container_name,
    )

    # Define the virtual host
    run_isql(
        f"DB.DBA.VHOST_DEFINE(vhost=>'{vhost}', lhost=>'{lhost}', lpath=>'{lpath}', "
        f"ppath=>'/!sparql/', is_dav=>1, vsp_user=>'dba',"
        f"opts=>vector('browse_sheet', '', 'noinherit', 'yes'));",
        isql_path,
        container_name,
    )

    sh_host = f"{resolved_vhost}:{resolved_port}"
    run_isql(
        f"INSERT SOFT DB.DBA.SYS_SPARQL_HOST (SH_HOST, SH_GRAPH_URI) VALUES ('{sh_host}', '{member_iri}');",
        isql_path,
        container_name,
    )

    return f"http://{resolved_vhost}:{resolved_port}{lpath}"


def ingest_batch(config: BenchmarkConfig, batch_id: int) -> Path:
    """Ingest all .nq files for a given batch and register SPARQL endpoints.

    Writes virtuoso-proxy-mapping-batch{batch_id}.json and returns its path.
    """
    gen = config.generation
    virt = gen.virtuoso
    workdir = Path(gen.workdir)
    dataset_dir = Path(virt.data_dir)

    container_name = f"docker-{virt.service_name}-1"
    isql_path = virt.isql
    container_data_path = "/usr/share/proj"

    grant_permissions(container_name, isql_path)

    fed_members = virt.federation_members.get(f"batch{batch_id}", {})

    for member_name, member_iri in fed_members.items():
        nq_file = dataset_dir / f"{member_name}.nq"
        if nq_file.exists():
            load_nq_file(nq_file, member_iri, isql_path, container_name, container_data_path)

    proxy_mapping: dict[str, str] = {}
    for member_name, member_iri in fed_members.items():
        lpath = f"/{member_name}/sparql"
        endpoint_url = register_sparql_endpoint(
            member_iri,
            lpath,
            isql_path,
            container_name,
            vport=virt.port,
        )
        proxy_mapping[member_iri] = endpoint_url

    mapping_file = workdir / f"virtuoso-proxy-mapping-batch{batch_id}.json"
    mapping_file.parent.mkdir(parents=True, exist_ok=True)
    mapping_file.write_text(json.dumps(proxy_mapping, indent=2))

    return mapping_file
