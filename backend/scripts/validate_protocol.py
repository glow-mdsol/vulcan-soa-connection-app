"""Drift guard for the WIP SoA IG: fail loudly at load time, not mid-demo."""

import argparse
import asyncio
import sys

import httpx

from vulcan_soa.config import Settings
from vulcan_soa.fhir_client import FhirClient


async def validate(client: FhirClient, protocol_id: str) -> list[str]:
    errors: list[str] = []
    protocol = await client.read("PlanDefinition", protocol_id)
    for action in protocol.get("action", []):
        if not action.get("id"):
            errors.append(f"protocol action without id (title={action.get('title')!r})")
            continue
        uri = action.get("definitionUri", "")
        if not uri.startswith("PlanDefinition/"):
            continue
        try:
            visit_pd = await client.read("PlanDefinition", uri.split("/", 1)[1])
        except httpx.HTTPStatusError:
            errors.append(f"{action['id']}: unresolvable {uri}")
            continue
        for visit_action in visit_pd.get("action", []):
            definition_uri = visit_action.get("definitionUri", "")
            if not definition_uri.startswith("ActivityDefinition/"):
                continue
            try:
                await client.read("ActivityDefinition", definition_uri.split("/", 1)[1])
            except httpx.HTTPStatusError:
                errors.append(f"{uri}: unresolvable {definition_uri}")
    return errors


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol_id", help="PlanDefinition id of the protocol design")
    args = parser.parse_args()

    settings = Settings()
    client = FhirClient(
        base_url=settings.fhir_base_url,
        basic_auth=(settings.smart_client_id, settings.smart_client_secret),
    )
    try:
        errors = await validate(client, args.protocol_id)
    finally:
        await client.close()

    for error in errors:
        print(f"DRIFT: {error}", file=sys.stderr)
    if errors:
        sys.exit(1)
    print(f"OK: {args.protocol_id} and its visit/activity definitions all resolve")


if __name__ == "__main__":
    asyncio.run(main())
