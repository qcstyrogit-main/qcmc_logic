import frappe

@frappe.whitelist(allow_guest=True)
def get_bot_topics():
    greetings = frappe.db.get_single_value("Chatbot Settings", "greetings") or ""
    topics = frappe.get_all(
        "Chatbot Topic",
        filters={"is_active": 1},
        fields=["name", "label", "reply"],
        order_by="idx asc"
    )
    return {
        "greetings": greetings,
        "topics": [
            {
                "id": t.name,
                "label": t.label,
                "reply": t.reply
            } for t in topics
        ]
    }