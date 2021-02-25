from trustix_proto import trustix_pb2_grpc  # type: ignore
from trustix_api import api_pb2
from fastapi.templating import (
    Jinja2Templates,
)
from fastapi.responses import (
    HTMLResponse,
)
from fastapi import (
    FastAPI,
    Request,
)
from typing import (
    Optional,
    Dict,
    List,
    Set,
)
from trustix_dash.models import (
    DerivationOutput,
    DerivationAttr,
)
from tortoise import Tortoise
import urllib.parse
import requests
import tempfile
import asyncio
import os.path
import shlex
import json
import grpc  # type: ignore

from trustix_dash.api import (
    get_derivation_output_results,
    get_derivation_outputs,
    evaluation_list,
)

BINARY_CACHE_PROXY = "http://localhost:8080"

TRUSTIX_RPC = "unix:../../sock"
channel = grpc.aio.insecure_channel(TRUSTIX_RPC)
stub = trustix_pb2_grpc.TrustixCombinedRPCStub(channel)


templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)


app = FastAPI()


@app.on_event("startup")
async def startup_event():
    await Tortoise.init(
        {
            "connections": {
                "default": "sqlite://db.sqlite3",
            },
            "apps": {
                "trustix_dash": {
                    "models": ["trustix_dash.models"],
                }
            },
            "use_tz": False,
            "timezone": "UTC",
        }
    )


@app.on_event("shutdown")
async def close_orm():
    await Tortoise.close_connections()


async def make_context(
    request: Request,
    title: str = "",
    selected_evaluation: Optional[str] = None,
    extra: Optional[Dict] = None,
) -> Dict:

    evaluations = await evaluation_list()
    if selected_evaluation and selected_evaluation not in evaluations:
        evaluations.insert(0, selected_evaluation)

    if not selected_evaluation:
        try:
            selected_evaluation = evaluations[0]
        except IndexError:
            pass

    ctx = {
        "evaluations": evaluations,
        "selected_evaluation": selected_evaluation,
        "request": request,
        "title": "Trustix R13Y" + (" ".join((" - ", title)) if title else ""),
        "drv_placeholder": "hello.x86_64-linux",
    }

    if extra:
        ctx.update(extra)

    return ctx


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    ctx = await make_context(request)
    return templates.TemplateResponse("index.jinja2", ctx)


@app.get("/drv/{drv_path}", response_class=HTMLResponse)
async def drv(request: Request, drv_path: str):

    drv_path = urllib.parse.unquote(drv_path)
    drvs = await get_derivation_outputs(drv_path)

    unreproduced_paths: Dict[str, List[str]] = {}
    reproduced_paths: Dict[str, List[str]] = {}
    missing_paths: Dict[str, List[str]] = {}  # Paths not built by any known log

    for drv in drvs:
        output: DerivationOutput
        for output in drv.derivationoutputs:  # type: ignore
            output_hashes: Set[bytes] = set(
                result.output_hash for result in output.derivationoutputresults  # type: ignore
            )

            if not output_hashes:
                missing_paths.setdefault(drv.drv, []).append(output.output)

            elif len(output_hashes) == 1:
                reproduced_paths.setdefault(drv.drv, []).append(output.output)

            elif len(output_hashes) > 1:
                unreproduced_paths.setdefault(drv.drv, []).append(output.output)

            else:
                raise RuntimeError("Logic error")

    ctx = await make_context(
        request,
        extra={
            "unreproduced_paths": unreproduced_paths,
            "reproduced_paths": reproduced_paths,
            "missing_paths": missing_paths,
        },
    )

    return templates.TemplateResponse("drv.jinja2", ctx)


# @app.post("/search")
# async def search(request: Request, attr: Optional[str] = None):
#     return {}


@app.get("/suggest/{attr}", response_model=List[str])
async def suggest(request: Request, attr: str):
    if len(attr) < 3:
        raise ValueError("Prefix too short")

    resp = await DerivationAttr.filter(attr__startswith=attr).only("attr")
    return [drv_attr.attr for drv_attr in resp]


@app.get("/diff/{output1}/{output2}", response_class=HTMLResponse)
async def diff(request: Request, output1: int, output2: int):
    result1, result2 = await get_derivation_output_results(output1, output2)

    # Uvloop has a nasty bug https://github.com/MagicStack/uvloop/issues/317
    # To work around this we run the fetching/unpacking in a separate blocking thread
    def fetch_unpack_nar(url, location):
        import subprocess

        loc_base = os.path.basename(location)
        loc_dir = os.path.dirname(location)

        try:
            os.mkdir(loc_dir)
        except FileExistsError:
            pass

        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            p = subprocess.Popen(["nix-nar-unpack", loc_base], stdin=subprocess.PIPE, cwd=loc_dir)
            for chunk in r.iter_content(chunk_size=512):
                p.stdin.write(chunk)
            p.stdin.close()
            p.wait(timeout=0.5)

        # Ensure correct mtime
        for subl in ((os.path.join(dirpath, f) for f in (dirnames + filenames)) for (dirpath, dirnames, filenames) in os.walk(location)):
            for path in subl:
                os.utime(path, (1, 1))
        os.utime(location, (1, 1))

    async def process_result(result, tmpdir, outbase) -> str:
        # Fetch narinfo
        narinfo = json.loads(
            (
                await stub.GetValue(api_pb2.ValueRequest(Digest=result.output_hash))
            ).Value
        )
        nar_hash = narinfo["narHash"].split(":")[-1]

        # Get store prefix
        output = await result.output

        store_base = output.store_path.split("/")[-1]
        store_prefix = store_base.split("-")[0]

        unpack_dir = os.path.join(tmpdir, store_base, outbase)
        nar_url = "/".join((BINARY_CACHE_PROXY, "nar", store_prefix, nar_hash))

        await asyncio.get_running_loop().run_in_executor(
            None, fetch_unpack_nar, nar_url, unpack_dir
        )

        return unpack_dir

    # TODO: Async tempfile
    with tempfile.TemporaryDirectory(prefix="trustix-ui-dash-diff") as tmpdir:
        dir_a, dir_b = await asyncio.gather(
            process_result(result1, tmpdir, "A"),
            process_result(result2, tmpdir, "B"),
        )

        dir_a_rel = os.path.join(os.path.basename(os.path.dirname(dir_a)), "A")
        dir_b_rel = os.path.join(os.path.basename(os.path.dirname(dir_b)), "B")

        proc = await asyncio.create_subprocess_shell(
            shlex.join(["diffoscope", "--html", "-", dir_a_rel, dir_b_rel]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmpdir,
        )
        stdout, stderr = await proc.communicate()

    # Diffoscope returns non-zero on paths that have a diff
    # Instead use stderr as a heurestic if the call went well or not
    if stderr:
        raise ValueError(stderr)

    return stdout
