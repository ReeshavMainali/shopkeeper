from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response
import sqlite3
import csv
import io
from datetime import datetime

app = Flask(__name__)
app.secret_key = "shopkeeper-secret-2024"

DB = "shop.db"

# ─── DB SETUP ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sku TEXT UNIQUE,
            category TEXT,
            price REAL NOT NULL,
            cost REAL DEFAULT 0,
            stock INTEGER NOT NULL DEFAULT 0,
            low_stock_threshold INTEGER DEFAULT 5,
            unit TEXT DEFAULT 'pcs',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            address TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER REFERENCES customers(id),
            customer_name TEXT,
            total REAL NOT NULL,
            paid REAL DEFAULT 0,
            status TEXT DEFAULT 'paid',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER REFERENCES sales(id) ON DELETE CASCADE,
            product_id INTEGER REFERENCES products(id),
            product_name TEXT NOT NULL,
            qty INTEGER NOT NULL,
            price REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tabs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER REFERENCES customers(id),
            product_id INTEGER REFERENCES products(id),
            product_name TEXT NOT NULL,
            qty INTEGER NOT NULL,
            price REAL NOT NULL,
            opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'open'
        );
        """)

init_db()

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def get_low_stock_count():
    db = get_db()
    result = db.execute("SELECT COUNT(*) as c FROM products WHERE stock <= low_stock_threshold").fetchone()
    db.close()
    return result["c"]

# ─── DASHBOARD ───────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    db = get_db()
    stats = {
        "products": db.execute("SELECT COUNT(*) as c FROM products").fetchone()["c"],
        "customers": db.execute("SELECT COUNT(*) as c FROM customers").fetchone()["c"],
        "low_stock": db.execute("SELECT COUNT(*) as c FROM products WHERE stock <= low_stock_threshold").fetchone()["c"],
        "today_sales": db.execute(
            "SELECT COALESCE(SUM(total),0) as s FROM sales WHERE DATE(created_at)=DATE('now')"
        ).fetchone()["s"],
        "open_tabs": db.execute("SELECT COUNT(*) as c FROM tabs WHERE status='open'").fetchone()["c"],
        "month_sales": db.execute(
            "SELECT COALESCE(SUM(total),0) as s FROM sales WHERE strftime('%Y-%m',created_at)=strftime('%Y-%m','now')"
        ).fetchone()["s"],
    }
    low_stock_items = db.execute(
        "SELECT * FROM products WHERE stock <= low_stock_threshold ORDER BY stock ASC LIMIT 5"
    ).fetchall()
    recent_sales = db.execute(
        "SELECT * FROM sales ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    db.close()
    return render_template("dashboard.html", stats=stats, low_stock_items=low_stock_items, recent_sales=recent_sales)

# ─── PRODUCTS ────────────────────────────────────────────────────────────────

@app.route("/products")
def products():
    db = get_db()
    q = request.args.get("q", "")
    cat = request.args.get("cat", "")
    query = "SELECT * FROM products WHERE 1=1"
    params = []
    if q:
        query += " AND (name LIKE ? OR sku LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if cat:
        query += " AND category=?"
        params.append(cat)
    query += " ORDER BY name"
    items = db.execute(query, params).fetchall()
    categories = db.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL").fetchall()
    db.close()
    low = get_low_stock_count()
    return render_template("products.html", items=items, categories=categories, q=q, cat=cat, low_stock_count=low)

@app.route("/products/add", methods=["GET","POST"])
def add_product():
    if request.method == "POST":
        db = get_db()
        db.execute("""INSERT INTO products (name,sku,category,price,cost,stock,low_stock_threshold,unit)
                      VALUES (?,?,?,?,?,?,?,?)""",
            (request.form["name"], request.form.get("sku") or None,
             request.form.get("category"), float(request.form["price"]),
             float(request.form.get("cost") or 0), int(request.form["stock"]),
             int(request.form.get("low_stock_threshold") or 5),
             request.form.get("unit","pcs")))
        db.commit()
        db.close()
        flash("Product added!", "success")
        return redirect(url_for("products"))
    return render_template("product_form.html", product=None)

@app.route("/products/edit/<int:pid>", methods=["GET","POST"])
def edit_product(pid):
    db = get_db()
    product = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if request.method == "POST":
        db.execute("""UPDATE products SET name=?,sku=?,category=?,price=?,cost=?,stock=?,
                      low_stock_threshold=?,unit=? WHERE id=?""",
            (request.form["name"], request.form.get("sku") or None,
             request.form.get("category"), float(request.form["price"]),
             float(request.form.get("cost") or 0), int(request.form["stock"]),
             int(request.form.get("low_stock_threshold") or 5),
             request.form.get("unit","pcs"), pid))
        db.commit()
        db.close()
        flash("Product updated!", "success")
        return redirect(url_for("products"))
    db.close()
    return render_template("product_form.html", product=product)

@app.route("/products/delete/<int:pid>", methods=["POST"])
def delete_product(pid):
    db = get_db()
    db.execute("DELETE FROM products WHERE id=?", (pid,))
    db.commit()
    db.close()
    flash("Product deleted.", "info")
    return redirect(url_for("products"))

# ─── CUSTOMERS ───────────────────────────────────────────────────────────────

@app.route("/customers")
def customers():
    db = get_db()
    q = request.args.get("q", "")
    query = "SELECT * FROM customers WHERE 1=1"
    params = []
    if q:
        query += " AND (name LIKE ? OR phone LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    items = db.execute(query + " ORDER BY name", params).fetchall()
    db.close()
    return render_template("customers.html", items=items, q=q)

@app.route("/customers/add", methods=["GET","POST"])
def add_customer():
    if request.method == "POST":
        db = get_db()
        db.execute("INSERT INTO customers (name,phone,address,notes) VALUES (?,?,?,?)",
            (request.form["name"], request.form.get("phone"),
             request.form.get("address"), request.form.get("notes")))
        db.commit()
        db.close()
        flash("Customer added!", "success")
        return redirect(url_for("customers"))
    return render_template("customer_form.html", customer=None)

@app.route("/customers/edit/<int:cid>", methods=["GET","POST"])
def edit_customer(cid):
    db = get_db()
    customer = db.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    if request.method == "POST":
        db.execute("UPDATE customers SET name=?,phone=?,address=?,notes=? WHERE id=?",
            (request.form["name"], request.form.get("phone"),
             request.form.get("address"), request.form.get("notes"), cid))
        db.commit()
        db.close()
        flash("Customer updated!", "success")
        return redirect(url_for("customers"))
    db.close()
    return render_template("customer_form.html", customer=customer)

@app.route("/customers/<int:cid>")
def customer_detail(cid):
    db = get_db()
    customer = db.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    sales = db.execute(
        "SELECT * FROM sales WHERE customer_id=? ORDER BY created_at DESC", (cid,)
    ).fetchall()
    tabs = db.execute(
        "SELECT t.*, p.unit FROM tabs t LEFT JOIN products p ON t.product_id=p.id WHERE t.customer_id=? AND t.status='open' ORDER BY t.opened_at DESC", (cid,)
    ).fetchall()
    tab_total = sum(t["qty"] * t["price"] for t in tabs)
    db.close()
    return render_template("customer_detail.html", customer=customer, sales=sales, tabs=tabs, tab_total=tab_total)

# ─── SALES ───────────────────────────────────────────────────────────────────

@app.route("/sales")
def sales():
    db = get_db()
    items = db.execute("SELECT * FROM sales ORDER BY created_at DESC LIMIT 100").fetchall()
    db.close()
    return render_template("sales.html", items=items)

@app.route("/sales/new", methods=["GET","POST"])
def new_sale():
    db = get_db()
    if request.method == "POST":
        data = request.get_json()
        customer_id = data.get("customer_id") or None
        customer_name = data.get("customer_name", "Walk-in")
        items = data.get("items", [])
        paid = float(data.get("paid", 0))
        notes = data.get("notes", "")

        total = sum(i["qty"] * i["price"] for i in items)
        status = "paid" if paid >= total else ("partial" if paid > 0 else "unpaid")

        sale_id = db.execute(
            "INSERT INTO sales (customer_id,customer_name,total,paid,status,notes) VALUES (?,?,?,?,?,?)",
            (customer_id, customer_name, total, paid, status, notes)
        ).lastrowid

        for item in items:
            db.execute(
                "INSERT INTO sale_items (sale_id,product_id,product_name,qty,price) VALUES (?,?,?,?,?)",
                (sale_id, item["product_id"], item["product_name"], item["qty"], item["price"])
            )
            db.execute("UPDATE products SET stock=stock-? WHERE id=?", (item["qty"], item["product_id"]))

        db.commit()
        db.close()
        return jsonify({"success": True, "sale_id": sale_id})

    products = db.execute("SELECT * FROM products WHERE stock > 0 ORDER BY name").fetchall()
    customers = db.execute("SELECT * FROM customers ORDER BY name").fetchall()
    db.close()
    return render_template("new_sale.html", products=products, customers=customers)

@app.route("/sales/<int:sid>")
def sale_detail(sid):
    db = get_db()
    sale = db.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
    items = db.execute("SELECT * FROM sale_items WHERE sale_id=?", (sid,)).fetchall()
    db.close()
    return render_template("sale_detail.html", sale=sale, items=items)

@app.route("/sales/<int:sid>/bill")
def print_bill(sid):
    db = get_db()
    sale = db.execute("SELECT * FROM sales WHERE id=?", (sid,)).fetchone()
    items = db.execute("SELECT * FROM sale_items WHERE sale_id=?", (sid,)).fetchall()
    db.close()
    return render_template("bill.html", sale=sale, items=items)

# ─── TABS ────────────────────────────────────────────────────────────────────

@app.route("/tabs")
def tabs():
    db = get_db()
    open_tabs = db.execute("""
        SELECT t.*, c.name as customer_name, c.phone as customer_phone
        FROM tabs t JOIN customers c ON t.customer_id=c.id
        WHERE t.status='open' ORDER BY t.opened_at DESC
    """).fetchall()

    # Group by customer
    by_customer = {}
    for tab in open_tabs:
        cid = tab["customer_id"]
        if cid not in by_customer:
            by_customer[cid] = {"name": tab["customer_name"], "phone": tab["customer_phone"], "items": [], "total": 0}
        by_customer[cid]["items"].append(tab)
        by_customer[cid]["total"] += tab["qty"] * tab["price"]

    db.close()
    return render_template("tabs.html", by_customer=by_customer)

@app.route("/tabs/add", methods=["GET","POST"])
def add_tab():
    db = get_db()
    if request.method == "POST":
        db.execute(
            "INSERT INTO tabs (customer_id,product_id,product_name,qty,price) VALUES (?,?,?,?,?)",
            (request.form["customer_id"], request.form["product_id"],
             request.form["product_name"], int(request.form["qty"]),
             float(request.form["price"]))
        )
        # Deduct stock
        db.execute("UPDATE products SET stock=stock-? WHERE id=?",
                   (int(request.form["qty"]), request.form["product_id"]))
        db.commit()
        db.close()
        flash("Tab opened!", "success")
        return redirect(url_for("tabs"))
    customers = db.execute("SELECT * FROM customers ORDER BY name").fetchall()
    products = db.execute("SELECT * FROM products WHERE stock > 0 ORDER BY name").fetchall()
    db.close()
    return render_template("add_tab.html", customers=customers, products=products)

@app.route("/tabs/close/<int:tid>", methods=["POST"])
def close_tab(tid):
    db = get_db()
    db.execute("UPDATE tabs SET status='closed' WHERE id=?", (tid,))
    db.commit()
    db.close()
    flash("Tab closed (marked paid).", "success")
    return redirect(url_for("tabs"))

@app.route("/tabs/close_customer/<int:cid>", methods=["POST"])
def close_customer_tabs(cid):
    db = get_db()
    db.execute("UPDATE tabs SET status='closed' WHERE customer_id=? AND status='open'", (cid,))
    db.commit()
    db.close()
    flash("All tabs closed for customer.", "success")
    return redirect(url_for("tabs"))

# ─── EXPORT ──────────────────────────────────────────────────────────────────

@app.route("/export/products")
def export_products():
    db = get_db()
    rows = db.execute("SELECT name,sku,category,price,cost,stock,unit FROM products").fetchall()
    db.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name","SKU","Category","Price","Cost","Stock","Unit"])
    for r in rows:
        writer.writerow(list(r))
    resp = make_response(output.getvalue())
    resp.headers["Content-Disposition"] = "attachment; filename=products.csv"
    resp.headers["Content-Type"] = "text/csv"
    return resp

@app.route("/export/sales")
def export_sales():
    db = get_db()
    rows = db.execute("SELECT id,customer_name,total,paid,status,notes,created_at FROM sales ORDER BY created_at DESC").fetchall()
    db.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID","Customer","Total","Paid","Status","Notes","Date"])
    for r in rows:
        writer.writerow(list(r))
    resp = make_response(output.getvalue())
    resp.headers["Content-Disposition"] = "attachment; filename=sales.csv"
    resp.headers["Content-Type"] = "text/csv"
    return resp

# ─── API (for JS) ─────────────────────────────────────────────────────────────

@app.route("/api/product/<int:pid>")
def api_product(pid):
    db = get_db()
    p = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    db.close()
    if p:
        return jsonify(dict(p))
    return jsonify({}), 404

if __name__ == "__main__":
    app.run(debug=True)
