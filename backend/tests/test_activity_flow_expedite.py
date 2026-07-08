from types import SimpleNamespace

import pytest

from vulcan_soa import activity_flow
from vulcan_soa.activity_flow import PhaseError, expedite


def fake_workspace(phase: str | None):
    chains = {} if phase is None else {"E1": SimpleNamespace(phase=phase)}
    return SimpleNamespace(chains=chains)


def install_fakes(monkeypatch, phase: str | None):
    calls: list[tuple] = []

    async def fake_load_workspace(client, subject_id):
        return fake_workspace(phase)

    async def fake_promote(client, subject_id, action_id, to_intent):
        calls.append(("promote", to_intent))
        return {"payload": f"after-{to_intent}"}

    async def fake_schedule_visit(client, subject_id, action_id):
        calls.append(("schedule",))
        return {"payload": "after-schedule"}

    monkeypatch.setattr(activity_flow, "_load_workspace", fake_load_workspace)
    monkeypatch.setattr(activity_flow, "promote", fake_promote)
    monkeypatch.setattr(activity_flow, "schedule_visit", fake_schedule_visit)
    return calls


async def test_expedite_from_proposed_runs_all_three_gates_in_order(monkeypatch):
    calls = install_fakes(monkeypatch, "proposed")
    result = await expedite(None, "subj-1", "E1")
    assert calls == [("promote", "plan"), ("promote", "order"), ("schedule",)]
    assert result == {"payload": "after-schedule"}


async def test_expedite_from_planned_skips_plan(monkeypatch):
    calls = install_fakes(monkeypatch, "planned")
    await expedite(None, "subj-1", "E1")
    assert calls == [("promote", "order"), ("schedule",)]


async def test_expedite_from_ordered_only_schedules(monkeypatch):
    calls = install_fakes(monkeypatch, "ordered")
    result = await expedite(None, "subj-1", "E1")
    assert calls == [("schedule",)]
    assert result == {"payload": "after-schedule"}


async def test_expedite_from_scheduled_raises_phase_error(monkeypatch):
    calls = install_fakes(monkeypatch, "scheduled")
    with pytest.raises(PhaseError):
        await expedite(None, "subj-1", "E1")
    assert calls == []


async def test_expedite_unmaterialized_action_raises_value_error(monkeypatch):
    install_fakes(monkeypatch, None)
    with pytest.raises(ValueError):
        await expedite(None, "subj-1", "E1")
