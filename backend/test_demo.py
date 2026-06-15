from app.models.state import CustomerInput
from app.orchestrator.graph import orchestrator
from app.services.data_loader import load_customers

for c in load_customers():
    customer = CustomerInput(
        name=c["name"],
        dob=c["dob"],
        nationality=c["nationality"],
        occupation=c["occupation"],
        source_of_funds=c.get("source_of_funds", "") or "",
        id_number=c.get("id_number", ""),
    )
    state = orchestrator.run(customer)
    print(
        f"{c['id']} {c['name']:20s} expected={c['expected_risk']:6s} "
        f"score={state.risk_assessment['risk_score']:3d} decision={state.decision['status']}"
    )
