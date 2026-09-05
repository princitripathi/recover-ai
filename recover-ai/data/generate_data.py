"""Synthetic transaction data generator for RecoverAI demo."""
import csv
import random
import uuid
from datetime import datetime, timedelta, timezone

random.seed(42)

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Arjun", "Sai", "Reyansh", "Krishna", "Ishaan",
    "Shaurya", "Atharv", "Diya", "Ananya", "Priya", "Kavya", "Aanya", "Aadhya",
    "Nisha", "Riya", "Meera", "Tara", "Neha", "Pooja", "Simran", "Kavita",
    "Rohit", "Amit", "Suresh", "Rajesh", "Manoj", "Vikram", "Sanjay", "Deepak",
    "Rahul", "Vijay", "Suresh", "Prakash", "Sunil", "Ajay", "Mahesh", "Ramesh",
    "Kiran", "Sneha", "Divya", "Richa", "Swati", "Pallavi", "Madhuri", "Sunita",
    "Rekha", "Geeta", "Suman", "Aarti", "Neeta", "Jaya", "Usha", "Lata",
    "Vishal", "Nitin", "Mohan", "Ganesh", "Sachin", "Manish", "Ashok", "Ravi",
    "Pankaj", "Arun", "Jay", "Gaurav", "Harsh", "Tanvi", "Priti", "Monika",
    "Shruti", "Namrata", "Shikha", "Alka", "Anjali", "Bhavana", "Chitra", "Deepa",
    "Farhan", "Zoya", "Imran", "Tariq", "Nasreen", "Parveen", "Rubina", "Salim",
    "Vikas", "Anil", "Bharat", "Chetan", "Darshan", "Eknath", "Firoz", "Gopal",
    "Harish", "Indra", "Jagdish", "Kamal", "Laxman", "Madhav", "Nandkishor", "Omkar",
    "Pranav", "Rajiv", "Sagar", "Tushar", "Uday", "Vinod", "Wasim", "Yash",
]

LAST_NAMES = [
    "Sharma", "Verma", "Gupta", "Singh", "Kumar", "Reddy", "Patel", "Nair",
    "Iyer", "Mishra", "Pandey", "Tiwari", "Rao", "Mehta", "Joshi", "Desai",
    "Kapoor", "Chopra", "Malhotra", "Bhat", "Menon", "Shetty", "Gowda", "Naik",
    "Das", "Bose", "Banerjee", "Mukherjee", "Chatterjee", "Sen", "Ghosh", "Dutta",
    "Khan", "Qureshi", "Siddiqui", "Ansari", "Husain", "Farooqi", "Begum", "Sheikh",
    "Aggarwal", "Khanna", "Sinha", "Srivastava", "Chaubey", "Yadav", "Thakur", "Chauhan",
    "Prajapati", "Sahu", "Bharadwaj", "Shukla", "Dubey", "Tripathi", "Mishra", "Pandit",
    "Kulkarni", "Deshpande", "Purohit", "Bhat", " Kamat", "Fernandes", "D'Souza", "Dsouza",
]

PAYMENT_METHODS = ["upi", "credit_card", "debit_card", "netbanking", "wallet"]
PAYMENT_WEIGHTS = [0.30, 0.25, 0.20, 0.15, 0.10]

CURRENCIES = ["INR"]

# Status distribution: ~55% paid, ~18% failed, ~14% abandoned, ~8% pending, ~5% mixed
STATUS_OPTIONS = ["paid", "failed", "abandoned", "pending"]
STATUS_WEIGHTS = [0.55, 0.18, 0.14, 0.08]

FAILURE_REASONS = [
    "issuer_declined", "insufficient_funds", "card_expired", "bank_downtime",
    "checkout_timeout", "customer_inactive", "vpa_invalid", "transaction_limit_exceeded",
    "authentication_failed", "network_error", "expired_card", "do_not_honor",
    "generic_decline", "suspected_fraud", "invalid_amount", "duplicate_transaction",
]

FAILURE_WEIGHTS = [
    0.15, 0.12, 0.10, 0.08, 0.10, 0.07, 0.08, 0.06,
    0.07, 0.06, 0.05, 0.04, 0.03, 0.01, 0.01, 0.01,
]

# Amount ranges (INR)
AMOUNT_RANGES = [
    (100, 500, 0.15),
    (500, 2000, 0.25),
    (2000, 5000, 0.20),
    (5000, 10000, 0.18),
    (10000, 25000, 0.12),
    (25000, 50000, 0.07),
    (50000, 100000, 0.03),
]


def weighted_choice(options, weights):
    return random.choices(options, weights=weights, k=1)[0]


def generate_amount():
    low, high, _ = weighted_choice(AMOUNT_RANGES, [w for _, _, w in AMOUNT_RANGES])
    return round(random.uniform(low, high), 2)


def generate_customer_id(index):
    return f"CUS-{500 + index}"


def generate_transaction_id(index):
    return f"TXN-{1001 + index}"


def generate_checkout_session_id():
    return f"CS-{uuid.uuid4().hex[:12].upper()}"


def generate_failure_reason(status):
    if status == "paid":
        return ""
    if status == "pending":
        return random.choice(["bank_processing", "authorization_pending", "waiting_for_verification"])
    return weighted_choice(FAILURE_REASONS, FAILURE_WEIGHTS)


def generate_created_at(base_date, index):
    # Spread transactions over ~30 days
    offset_hours = int(index * 30 * 24 / 520) + random.randint(0, 6)
    dt = base_date + timedelta(hours=offset_hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")


def generate_row(index):
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    customer_name = f"{first} {last}"
    customer_id = generate_customer_id(index)
    txn_id = generate_transaction_id(index)
    amount = generate_amount()
    currency = "INR"
    status = weighted_choice(STATUS_OPTIONS, STATUS_WEIGHTS)
    payment_method = weighted_choice(PAYMENT_METHODS, PAYMENT_WEIGHTS)
    failure_reason = generate_failure_reason(status)
    created_at = generate_created_at(datetime(2026, 7, 1, tzinfo=timezone(timedelta(hours=5, minutes=30))), index)

    # New fields
    retry_count = random.choices([0, 1, 2, 3, 4, 5], weights=[0.35, 0.25, 0.18, 0.12, 0.07, 0.03])[0]
    if status == "paid":
        retry_count = 0

    previous_successful_payments = random.choices(
        [0, 1, 2, 3, 5, 8, 12, 20],
        weights=[0.20, 0.18, 0.15, 0.12, 0.13, 0.10, 0.08, 0.04],
    )[0]

    # Customer lifetime value correlates with previous payments
    base_clv = 2000 + previous_successful_payments * random.randint(800, 3000)
    customer_lifetime_value = round(min(base_clv * random.uniform(0.7, 1.4), 500000), 2)

    # Hours since event: spread from 1 to 720 (30 days)
    hours_since_event = random.randint(1, 720)

    checkout_session_id = generate_checkout_session_id()

    return {
        "id": txn_id,
        "customer_id": customer_id,
        "customer_name": customer_name,
        "amount": f"{amount:.2f}",
        "currency": currency,
        "status": status,
        "payment_method": payment_method,
        "failure_reason": failure_reason,
        "created_at": created_at,
        "retry_count": str(retry_count),
        "previous_successful_payments": str(previous_successful_payments),
        "customer_lifetime_value": f"{customer_lifetime_value:.2f}",
        "hours_since_event": str(hours_since_event),
        "checkout_session_id": checkout_session_id,
    }


def main():
    output_path = "demo_transactions.csv"
    fieldnames = [
        "id", "customer_id", "customer_name", "amount", "currency",
        "status", "payment_method", "failure_reason", "created_at",
        "retry_count", "previous_successful_payments", "customer_lifetime_value",
        "hours_since_event", "checkout_session_id",
    ]

    rows = []
    for i in range(520):
        rows.append(generate_row(i))

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Print stats
    statuses = {}
    methods = {}
    reasons = {}
    for row in rows:
        s = row["status"]
        statuses[s] = statuses.get(s, 0) + 1
        m = row["payment_method"]
        methods[m] = methods.get(m, 0) + 1
        r = row["failure_reason"]
        if r:
            reasons[r] = reasons.get(r, 0) + 1

    print(f"Generated {len(rows)} transactions")
    print(f"Status distribution: {statuses}")
    print(f"Payment methods: {methods}")
    print(f"Top failure reasons: {dict(sorted(reasons.items(), key=lambda x: -x[1])[:8])}")


if __name__ == "__main__":
    main()
