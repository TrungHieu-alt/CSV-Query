import csv
import random
from datetime import datetime, timedelta
from pathlib import Path


# =========================
# CONFIGURATION
# =========================

NUM_ORDERS = 1000

START_DATE = datetime(2025, 1, 1)
END_DATE = datetime(2025, 12, 31)

OUTPUT_FILE = Path("data/sales_data.csv")


# =========================
# PRODUCT DATA
# =========================

PRODUCTS = [
    {
        "name": "Laptop",
        "category": "Electronics",
        "price": 1500,
        "weight": 10
    },
    {
        "name": "Monitor",
        "category": "Electronics",
        "price": 350,
        "weight": 15
    },
    {
        "name": "Tablet",
        "category": "Electronics",
        "price": 600,
        "weight": 12
    },
    {
        "name": "Smartphone",
        "category": "Electronics",
        "price": 800,
        "weight": 20
    },
    {
        "name": "Keyboard",
        "category": "Accessories",
        "price": 60,
        "weight": 25
    },
    {
        "name": "Mouse",
        "category": "Accessories",
        "price": 25,
        "weight": 40
    },
    {
        "name": "Headphones",
        "category": "Accessories",
        "price": 100,
        "weight": 30
    },
    {
        "name": "Webcam",
        "category": "Accessories",
        "price": 80,
        "weight": 20
    }
]


# =========================
# REGION DATA
# =========================

REGIONS = [
    "Hanoi",
    "Ho Chi Minh City",
    "Da Nang",
    "Hai Phong",
    "Can Tho"
]

REGION_WEIGHTS = [
    35,  # Hanoi
    30,  # Ho Chi Minh City
    15,  # Da Nang
    10,  # Hai Phong
    10   # Can Tho
]


# =========================
# HELPER FUNCTIONS
# =========================

def generate_random_date():
    """Generate a random date between START_DATE and END_DATE."""

    total_days = (END_DATE - START_DATE).days

    random_days = random.randint(0, total_days)

    return START_DATE + timedelta(days=random_days)


def get_seasonal_multiplier(order_date):
    """
    Increase sales during the end-of-year shopping season.
    """

    if order_date.month in [11, 12]:
        return 1.25

    if order_date.month in [6, 7]:
        return 1.10

    return 1.0


def choose_product():
    """Choose a product using weighted random selection."""

    weights = [
        product["weight"]
        for product in PRODUCTS
    ]

    return random.choices(
        PRODUCTS,
        weights=weights,
        k=1
    )[0]


# =========================
# GENERATE CSV
# =========================

def generate_sales_data():

    # Create the data folder if it does not exist
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    fieldnames = [
        "order_id",
        "order_date",
        "product",
        "category",
        "region",
        "quantity",
        "unit_price",
        "revenue"
    ]

    with open(
        OUTPUT_FILE,
        mode="w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()

        for order_number in range(
            1,
            NUM_ORDERS + 1
        ):

            order_date = generate_random_date()

            product = choose_product()

            region = random.choices(
                REGIONS,
                weights=REGION_WEIGHTS,
                k=1
            )[0]

            seasonal_multiplier = (
                get_seasonal_multiplier(
                    order_date
                )
            )

            # Expensive products are usually purchased
            # in smaller quantities
            if product["price"] >= 500:

                quantity = random.randint(
                    1,
                    3
                )

            elif product["price"] >= 200:

                quantity = random.randint(
                    1,
                    5
                )

            else:

                quantity = random.randint(
                    1,
                    10
                )

            # Add a small price variation
            price_multiplier = random.uniform(
                0.90,
                1.05
            )

            unit_price = round(
                product["price"]
                * price_multiplier,
                2
            )

            revenue = round(
                quantity
                * unit_price
                * seasonal_multiplier,
                2
            )

            writer.writerow(
                {
                    "order_id": (
                        f"ORD{order_number:05d}"
                    ),
                    "order_date": (
                        order_date.strftime(
                            "%Y-%m-%d"
                        )
                    ),
                    "product": (
                        product["name"]
                    ),
                    "category": (
                        product["category"]
                    ),
                    "region": region,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "revenue": revenue
                }
            )

    print(
        f"Successfully created: {OUTPUT_FILE}"
    )

    print(
        f"Number of orders: {NUM_ORDERS}"
    )


# =========================
# RUN PROGRAM
# =========================

if __name__ == "__main__":
    generate_sales_data()
