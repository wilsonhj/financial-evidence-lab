#!/usr/bin/env python3
"""Allowlisted SSH operations on already provisioned dedicated Railway smoke services.

No deployment/provisioning or arbitrary command interface is provided. SSH host
keys and service instance IDs must be supplied independently by the operator.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

MODULE_ACTIONS = {
    "evals.harness.reader_prod_smoke": {"corrupt", "restore"},
    "evals.harness.reader_prod_smoke_service": {"stop", "start"},
}

# Fixed programs; all external values are positional arguments, never code.
API_PROGRAM = r"""
import json,os,pathlib,subprocess,sys
from urllib.parse import urlsplit
revision,target,manifest_path,api_url,module,action=sys.argv[1:]
assert os.environ.get("RAILWAY_PUBLIC_DOMAIN")==urlsplit(api_url).hostname
assert os.environ.get("RAILWAY_GIT_COMMIT_SHA")==revision, "deployed revision mismatch"
assert os.environ.get("FEL_READER_SMOKE_TARGET")==target, "dedicated target mismatch"
assert os.environ.get("FEL_READER_SMOKE_SERVICE_HOSTED")=="1", "hosted controller is not enabled"
assert os.environ.get("FEL_AUTH_MODE")=="mock", "smoke auth mode mismatch"
path=pathlib.Path(manifest_path)
manifest=json.loads(path.read_text())
assert manifest.get("target")==target and manifest.get("schema_version")=="reader-prod-smoke/v1"
storage=pathlib.Path(os.environ["FEL_STORAGE_DIR"])
assert (storage/".reader-smoke-target").read_text()==target
expected="schema_version target org user denied_user workspace entity as_of "
expected+="corpus pinned_corpus documents jobs"
assert set(manifest)==set(expected.split())
if action=="inspect":
    print(json.dumps({"revision":revision,"target":target,"manifest":manifest}))
elif action=="recover":
    subprocess.run([sys.executable,"-m","evals.harness.reader_prod_smoke_service","start","--manifest",manifest_path,"--dedicated-target",target],check=True,capture_output=True)
    if (storage/".reader-smoke-original").exists():
        subprocess.run([sys.executable,"-m","evals.harness.reader_prod_smoke","restore","--manifest",manifest_path,"--dedicated-target",target],check=True,capture_output=True)
else:
    allowed={"evals.harness.reader_prod_smoke":{"corrupt","restore"},"evals.harness.reader_prod_smoke_service":{"stop","start"}}
    assert action in allowed.get(module,set()), "operation refused"
    subprocess.run([sys.executable,"-m",module,action,"--manifest",manifest_path,"--dedicated-target",target],check=True,capture_output=True)
"""

WEB_PROGRAM = r"""
const [revision,target,api,org,user,workspace,entity,asof,variant,web]=process.argv.slice(1);
const assert=require('node:assert/strict');
assert.equal(process.env.RAILWAY_PUBLIC_DOMAIN,new URL(web).hostname);
assert.equal(process.env.RAILWAY_GIT_COMMIT_SHA,revision);
assert.equal(process.env.FEL_READER_SMOKE_TARGET,target);
assert.equal(process.env.FEL_EVIDENCE_SOURCE,'http');
assert.equal(process.env.FEL_API_BASE_URL,api);
assert.equal(process.env.FEL_WORKSPACE_ID,workspace);
assert.equal(process.env.FEL_ENTITY_IDS,entity);
assert.equal(process.env.FEL_AS_OF,asof);
const token=process.env.FEL_API_BEARER_TOKEN;
if(variant==='unauthorized'){assert.equal(token,'invalid');}
else {
assert.ok(token && token.startsWith('mock.'));
const claims=JSON.parse(Buffer.from(token.slice(5),'base64url').toString());
assert.equal(claims.org_id,org);assert.equal(claims.sub,user);assert.equal(claims.role,'owner');
}
console.log(JSON.stringify({revision,target,evidence_source:'http'}));
"""


def configuration() -> dict[str, str]:
    names = (
        "TARGET",
        "REVISION",
        "API_INSTANCE",
        "WEB_INSTANCE",
        "UNAUTHORIZED_WEB_INSTANCE",
        "FORBIDDEN_WEB_INSTANCE",
        "UNAUTHORIZED_WEB_URL",
        "FORBIDDEN_WEB_URL",
        "SSH_KEY",
        "KNOWN_HOSTS",
        "REMOTE_CWD",
        "REMOTE_PYTHON",
        "REMOTE_MANIFEST",
        "API_URL",
        "WEB_URL",
        "MANIFEST",
    )
    values = {name: os.environ["READER_SMOKE_" + name] for name in names}
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,79}", values["TARGET"]):
        raise ValueError("Invalid dedicated target")
    if os.environ.get("FEL_READER_SMOKE_TARGET") != values["TARGET"]:
        raise ValueError("Dedicated target mismatch")
    if not re.fullmatch(r"[0-9a-f]{40}", values["REVISION"]):
        raise ValueError("An exact reviewed revision is required")
    for name in (
        "API_INSTANCE",
        "WEB_INSTANCE",
        "UNAUTHORIZED_WEB_INSTANCE",
        "FORBIDDEN_WEB_INSTANCE",
    ):
        if str(UUID(values[name])) != values[name]:
            raise ValueError("Canonical Railway service instance IDs are required")
    if (
        len(
            {
                values[name]
                for name in (
                    "API_INSTANCE",
                    "WEB_INSTANCE",
                    "UNAUTHORIZED_WEB_INSTANCE",
                    "FORBIDDEN_WEB_INSTANCE",
                )
            }
        )
        != 4
    ):
        raise ValueError("API and web must be distinct dedicated services")
    for name in ("API_URL", "WEB_URL", "UNAUTHORIZED_WEB_URL", "FORBIDDEN_WEB_URL"):
        url = urlsplit(values[name])
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("Explicit HTTPS service URLs are required")
    for name in ("REMOTE_CWD", "REMOTE_PYTHON", "REMOTE_MANIFEST"):
        if not values[name].startswith("/") or any(c in values[name] for c in ("\0", "\n", "\r")):
            raise ValueError("Absolute remote paths without control characters are required")
    for name in ("SSH_KEY", "KNOWN_HOSTS"):
        if not Path(values[name]).is_file():
            raise ValueError("Pinned SSH credentials are required")
    return values


def remote_command(cwd: str, executable: str, arguments: list[str]) -> str:
    return "cd " + shlex.quote(cwd) + " && exec " + shlex.join([executable, *arguments])


def ssh(config: dict[str, str], instance: str, command: str) -> bytes:
    result = subprocess.run(
        [
            "ssh",
            "-F",
            "/dev/null",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "LogLevel=ERROR",
            "-o",
            "UserKnownHostsFile=" + config["KNOWN_HOSTS"],
            "-i",
            config["SSH_KEY"],
            instance + "@ssh.railway.com",
            command,
        ],
        capture_output=True,
        timeout=55,
        check=False,
    )
    if result.returncode or len(result.stdout) > 128 * 1024:
        # Neither SSH stderr nor a remote traceback may disclose service secrets.
        raise RuntimeError("Dedicated remote operation failed; inspect restricted service logs")
    return result.stdout


def api_operation(config: dict[str, str], module: str, action: str) -> bytes:
    command = remote_command(
        config["REMOTE_CWD"],
        config["REMOTE_PYTHON"],
        [
            "-I",
            "-c",
            API_PROGRAM,
            config["REVISION"],
            config["TARGET"],
            config["REMOTE_MANIFEST"],
            config["API_URL"],
            module,
            action,
        ],
    )
    return ssh(config, config["API_INSTANCE"], command)


def inspect(config: dict[str, str]) -> dict[str, Any]:
    proof: dict[str, Any] = json.loads(api_operation(config, "", "inspect"))
    if proof.get("target") != config["TARGET"] or proof.get("revision") != config["REVISION"]:
        raise ValueError("Remote proof does not match the approved target and revision")
    manifest = proof["manifest"]
    if manifest.get("target") != config["TARGET"]:
        raise ValueError("Remote manifest identifies a different target")
    for instance, variant, user in (
        ("WEB_INSTANCE", "owner", manifest["user"]),
        ("UNAUTHORIZED_WEB_INSTANCE", "unauthorized", manifest["user"]),
        ("FORBIDDEN_WEB_INSTANCE", "forbidden", manifest["denied_user"]),
    ):
        web = json.loads(
            ssh(
                config,
                config[instance],
                remote_command(
                    config["REMOTE_CWD"],
                    "node",
                    [
                        "-e",
                        WEB_PROGRAM,
                        config["REVISION"],
                        config["TARGET"],
                        config["API_URL"],
                        manifest["org"],
                        user,
                        manifest["workspace"],
                        manifest["entity"],
                        manifest["as_of"],
                        variant,
                        config[instance.replace("INSTANCE", "URL")],
                    ],
                ),
            )
        )
        if web != {
            "revision": config["REVISION"],
            "target": config["TARGET"],
            "evidence_source": "http",
        }:
            raise ValueError("Web deployment proof mismatch")
    return proof


def parse_operation(arguments: list[str], config: dict[str, str]) -> tuple[str, str]:
    if (
        len(arguments) != 7
        or arguments[0] != "-m"
        or arguments[3] != "--manifest"
        or arguments[5] != "--dedicated-target"
    ):
        raise ValueError("Only the browser smoke operation interface is supported")
    module, action = arguments[1:3]
    if action not in MODULE_ACTIONS.get(module, set()):
        raise ValueError("Remote operation is not allowlisted")
    if arguments[6] != config["TARGET"]:
        raise ValueError("Browser dedicated target mismatch")
    if Path(arguments[4]).resolve() != Path(config["MANIFEST"]).resolve():
        raise ValueError("Browser manifest path differs from the prepared manifest")
    return module, action


def main() -> None:
    config = configuration()
    arguments = sys.argv[1:]
    if arguments == ["--prepare"]:
        proof = inspect(config)
        path = Path(config["MANIFEST"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(proof["manifest"], indent=2) + "\n")
        path.with_suffix(".deployment-proof.json").write_text(
            json.dumps(
                {
                    "revision": proof["revision"],
                    "target": proof["target"],
                    "api_url": config["API_URL"],
                    "web_url": config["WEB_URL"],
                },
                indent=2,
            )
            + "\n"
        )
        return
    if arguments == ["--recover"]:
        api_operation(config, "", "recover")
        return
    module, action = parse_operation(arguments, config)
    # Bind each mutation to the exact manifest prepared from the deployed API.
    proof = json.loads(api_operation(config, "", "inspect"))
    if proof["manifest"] != json.loads(Path(config["MANIFEST"]).read_text()):
        raise ValueError("Deployed manifest changed since preparation")
    api_operation(config, module, action)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Dedicated reader smoke remote execution failed; no remote output exposed"
        ) from None
