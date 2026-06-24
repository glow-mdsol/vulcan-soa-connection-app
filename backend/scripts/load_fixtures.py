import argparse
import asyncio
import json
from pathlib import Path

from vulcan_soa.config import Settings
from vulcan_soa.fhir_client import FhirClient


async def load_directory(client: FhirClient, directory: Path) -> list[tuple[Path, str]]:
    results: list[tuple[Path, str]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            resource = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            results.append((path, f"SKIP: invalid JSON ({exc})"))
            continue

        if not isinstance(resource, dict):
            results.append((path, f"SKIP: not a single FHIR resource (got {type(resource).__name__})"))
            continue

        resource_type = resource.get("resourceType")
        resource_id = resource.get("id")
        if not resource_type or not resource_id:
            results.append((path, "SKIP: missing resourceType or id"))
            continue

        try:
            await client.put_by_id(resource_type, resource_id, resource)
            results.append((path, "OK"))
        except Exception as exc:  # noqa: BLE001 - intentionally broad: log and continue loading the rest
            results.append((path, f"FAIL: {exc}"))

    return results


async def main() -> None:
    parser = argparse.ArgumentParser(description="Load FHIR resource JSON files into Aidbox")
    parser.add_argument("directory", type=Path, help="Directory of *.json FHIR resource files")
    args = parser.parse_args()

    settings = Settings()
    client = FhirClient(
        base_url=settings.fhir_base_url,
        basic_auth=(settings.smart_client_id, settings.smart_client_secret),
    )
    try:
        results = await load_directory(client, args.directory)
    finally:
        await client.close()

    for path, outcome in results:
        print(f"{outcome:40s} {path.name}")


if __name__ == "__main__":
    asyncio.run(main())
