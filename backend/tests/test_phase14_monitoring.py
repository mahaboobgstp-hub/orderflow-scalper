from app.services.monitoring import MonitoringService

def test_health_payload_reports_operational_basics():
    service=MonitoringService()
    payload=service.health()
    assert payload["status"]=="ok"
    assert payload["service"]=="orderflow-scalper-api"
    assert payload["uptime_seconds"]>=0

def test_events_are_bounded_and_retrievable():
    service=MonitoringService()
    service.max_events=3
    for i in range(5): service.record("INFO","test_event",{"n":i})
    result=service.recent_events(3)
    assert result["count"]==3
    assert [e["details"]["n"] for e in result["events"]]==[2,3,4]

def test_diagnostics_reports_missing_component_as_degraded():
    class State: pass
    class FakeApp: state=State()
    service=MonitoringService()
    payload=service.diagnostics(FakeApp())
    assert payload["status"]=="degraded"
