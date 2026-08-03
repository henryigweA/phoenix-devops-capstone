"""
Phoenix Inventory API
----------------------
A deliberately tiny REST API for the DevOps capstone project.
This file is FROZEN — the "developer's" work is done. Everything from
here on (Docker, Terraform, CI/CD, monitoring) is the DevOps engineer's job.

Endpoints:
  GET  /health              -> liveness check
  GET  /products             -> list all products
  GET  /products/<id>        -> get one product
  POST /products             -> add a product
"""

from flask import Flask, jsonify, request
import itertools

app = Flask(__name__)

# In-memory "database" — resets every time the app restarts.
# (A real database is a stretch goal, not part of this build.)
_id_counter = itertools.count(1)
products = {}


def _seed():
    for name, qty in [("Widget", 100), ("Gadget", 50), ("Gizmo", 25)]:
        pid = next(_id_counter)
        products[pid] = {"id": pid, "name": name, "quantity": qty}


_seed()

@app.get("/health")
def health():
    return jsonify(status="ok", version="1.1"), 200


@app.get("/products")
def list_products():
    return jsonify(list(products.values())), 200


@app.get("/products/<int:product_id>")
def get_product(product_id):
    product = products.get(product_id)
    if not product:
        return jsonify(error="not found"), 404
    return jsonify(product), 200


@app.post("/products")
def add_product():
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    quantity = data.get("quantity")

    if not name or not isinstance(quantity, int):
        return jsonify(error="name (string) and quantity (int) are required"), 400

    pid = next(_id_counter)
    product = {"id": pid, "name": name, "quantity": quantity}
    products[pid] = product
    return jsonify(product), 201


if __name__ == "__main__":
    # 0.0.0.0 = listen on all interfaces, not just localhost.
    # Remember Lesson: without this, nothing outside the container/VM
    # can ever reach it, even with a perfect public IP and open NSG.
    app.run(host="0.0.0.0", port=5000)
