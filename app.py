from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
import sqlite3
from datetime import datetime
import re
import hashlib
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'restaurant_secret_key_987654321'

# Configure upload folder
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Ensure upload folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Check allowed file extensions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Initialize SQLite database
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # Tables
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'staff'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS menu_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        description TEXT,
        image_path TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS tables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number INTEGER NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'free'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_id INTEGER,
        user_id INTEGER,
        status TEXT NOT NULL DEFAULT 'pending',
        total REAL NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (table_id) REFERENCES tables (id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        menu_item_id INTEGER,
        quantity INTEGER NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders (id),
        FOREIGN KEY (menu_item_id) REFERENCES menu_items (id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        quantity REAL NOT NULL,
        unit TEXT NOT NULL,
        low_stock_threshold REAL NOT NULL DEFAULT 10.0
    )''')
    # Insert default admin user
    c.execute("SELECT COUNT(*) FROM users WHERE email = 'adminuser@gmail.com'")
    if c.fetchone()[0] == 0:
        hashed_password = hashlib.sha256('admin@123'.encode()).hexdigest()
        c.execute("INSERT INTO users (email, password, name, role) VALUES (?, ?, ?, ?)",
                  ('adminuser@gmail.com', hashed_password, 'Admin', 'admin'))
    # Insert sample menu items
    c.execute("SELECT COUNT(*) FROM menu_items")
    if c.fetchone()[0] == 0:
        sample_menu = [
            ('Margherita Pizza', 12.99, 'Classic pizza with tomato and mozzarella', None),
            ('Grilled Salmon', 18.50, 'Fresh salmon with herbs', None),
            ('Caesar Salad', 8.99, 'Crisp romaine with Caesar dressing', None)
        ]
        c.executemany("INSERT INTO menu_items (name, price, description, image_path) VALUES (?, ?, ?, ?)", sample_menu)
    # Insert 50 tables
    c.execute("SELECT COUNT(*) FROM tables")
    if c.fetchone()[0] == 0:
        sample_tables = [(i, 'free') for i in range(1, 51)]
        c.executemany("INSERT INTO tables (number, status) VALUES (?, ?)", sample_tables)
    # Insert sample inventory
    c.execute("SELECT COUNT(*) FROM inventory")
    if c.fetchone()[0] == 0:
        sample_inventory = [
            ('Tomato Sauce', 50.0, 'liters', 10.0),
            ('Mozzarella', 20.0, 'kg', 5.0),
            ('Salmon', 10.0, 'kg', 2.0)
        ]
        c.executemany("INSERT INTO inventory (name, quantity, unit, low_stock_threshold) VALUES (?, ?, ?, ?)", sample_inventory)
    conn.commit()
    conn.close()

# Validate email
def is_valid_email(email):
    return re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email)

# Login required decorator
def login_required(f):
    def wrap(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

# Admin required decorator
def admin_required(f):
    def wrap(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            abort(404)
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

# Home page - Order overview with side-scrolling menu
@app.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 5
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM orders")
    total_orders = c.fetchone()[0]
    total_pages = (total_orders + per_page - 1) // per_page
    c.execute("SELECT o.id, t.number, o.status, o.total, o.created_at FROM orders o JOIN tables t ON o.table_id = t.id ORDER BY o.created_at DESC LIMIT ? OFFSET ?",
              (per_page, (page - 1) * per_page))
    orders = c.fetchall()
    c.execute("SELECT id, name, price, description, image_path FROM menu_items")
    menu_items = c.fetchall()
    c.execute("SELECT id, number FROM tables WHERE status = 'free'")
    tables = c.fetchall()
    conn.close()
    return render_template('index.html', orders=orders, page=page, total_pages=total_pages, menu_items=menu_items, tables=tables)

# Create order from home page
@app.route('/order/create_from_home', methods=['POST'])
@login_required
def order_create_from_home():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    table_id = request.form['table_id']
    item_ids = request.form.getlist('item_id')
    quantities = request.form.getlist('quantity')
    if not table_id or not item_ids or not quantities:
        flash('All fields are required.', 'error')
    else:
        total = 0
        c.execute("SELECT price FROM menu_items WHERE id IN ({})".format(','.join('?' * len(item_ids))), item_ids)
        prices = c.fetchall()
        for price, qty in zip(prices, quantities):
            total += float(price[0]) * int(qty)
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("INSERT INTO orders (table_id, user_id, status, total, created_at) VALUES (?, ?, ?, ?, ?)",
                  (table_id, session['user_id'], 'pending', total, created_at))
        order_id = c.lastrowid
        for item_id, qty in zip(item_ids, quantities):
            if int(qty) > 0:  # Only insert items with quantity > 0
                c.execute("INSERT INTO order_items (order_id, menu_item_id, quantity) VALUES (?, ?, ?)",
                          (order_id, item_id, qty))
        c.execute("UPDATE tables SET status = 'occupied' WHERE id = ?", (table_id,))
        conn.commit()
        flash('Order created successfully!', 'success')
    conn.close()
    return redirect(url_for('index'))

# Create new order
@app.route('/order/create', methods=['GET', 'POST'])
@login_required
def order_create():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, number FROM tables WHERE status = 'free'")
    tables = c.fetchall()
    c.execute("SELECT id, name, price, description, image_path FROM menu_items")
    menu_items = c.fetchall()
    if request.method == 'POST':
        table_id = request.form['table_id']
        item_ids = request.form.getlist('item_id')
        quantities = request.form.getlist('quantity')
        if not table_id or not item_ids or not quantities:
            flash('All fields are required.', 'error')
        else:
            total = 0
            c.execute("SELECT price FROM menu_items WHERE id IN ({})".format(','.join('?' * len(item_ids))), item_ids)
            prices = c.fetchall()
            for price, qty in zip(prices, quantities):
                total += float(price[0]) * int(qty)
            created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute("INSERT INTO orders (table_id, user_id, status, total, created_at) VALUES (?, ?, ?, ?, ?)",
                      (table_id, session['user_id'], 'pending', total, created_at))
            order_id = c.lastrowid
            for item_id, qty in zip(item_ids, quantities):
                if int(qty) > 0:
                    c.execute("INSERT INTO order_items (order_id, menu_item_id, quantity) VALUES (?, ?, ?)",
                              (order_id, item_id, qty))
            c.execute("UPDATE tables SET status = 'occupied' WHERE id = ?", (table_id,))
            conn.commit()
            flash('Order created successfully!', 'success')
            return redirect(url_for('index'))
    conn.close()
    return render_template('order_create.html', tables=tables, menu_items=menu_items)

# Order details
@app.route('/order/<int:order_id>')
@login_required
def order_detail(order_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT o.id, t.number, o.status, o.total, o.created_at FROM orders o JOIN tables t ON o.table_id = t.id WHERE o.id = ?", (order_id,))
    order = c.fetchone()
    if not order:
        abort(404)
    c.execute("SELECT m.name, m.price, oi.quantity FROM order_items oi JOIN menu_items m ON oi.menu_item_id = m.id WHERE oi.order_id = ?", (order_id,))
    items = c.fetchall()
    conn.close()
    return render_template('order_detail.html', order=order, items=items)

# Update order status
@app.route('/order/update/<int:order_id>', methods=['POST'])
@login_required
def order_update(order_id):
    status = request.form['status']
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT table_id FROM orders WHERE id = ?", (order_id,))
    table_id = c.fetchone()
    if not table_id:
        abort(404)
    c.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    if status == 'completed':
        c.execute("UPDATE tables SET status = 'free' WHERE id = ?", (table_id[0],))
    conn.commit()
    conn.close()
    flash('Order status updated!', 'success')
    return redirect(url_for('order_detail', order_id=order_id))

# Table management
@app.route('/tables')
@login_required
def table_manage():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, number, status FROM tables ORDER BY number")
    tables = c.fetchall()
    conn.close()
    return render_template('table_manage.html', tables=tables)

# Update table status
@app.route('/table/update/<int:table_id>', methods=['POST'])
@login_required
def table_update(table_id):
    new_status = request.form['status']
    if new_status not in ['free', 'occupied']:
        flash('Invalid status.', 'error')
        return redirect(url_for('table_manage'))
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("UPDATE tables SET status = ? WHERE id = ?", (new_status, table_id))
    conn.commit()
    conn.close()
    flash('Table status updated!', 'success')
    return redirect(url_for('table_manage'))

# Inventory management
@app.route('/inventory', methods=['GET', 'POST'])
@login_required
def inventory():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    if request.method == 'POST':
        name = request.form['name']
        quantity = request.form['quantity']
        unit = request.form['unit']
        threshold = request.form['threshold']
        if not name or not quantity or not unit or not threshold:
            flash('All fields are required.', 'error')
        else:
            c.execute("INSERT INTO inventory (name, quantity, unit, low_stock_threshold) VALUES (?, ?, ?, ?)",
                      (name, quantity, unit, threshold))
            conn.commit()
            flash('Inventory item added!', 'success')
    c.execute("SELECT id, name, quantity, unit, low_stock_threshold FROM inventory")
    items = c.fetchall()
    conn.close()
    return render_template('inventory.html', items=items)

# Update inventory
@app.route('/inventory/update/<int:item_id>', methods=['POST'])
@login_required
def inventory_update(item_id):
    quantity = request.form['quantity']
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("UPDATE inventory SET quantity = ? WHERE id = ?", (quantity, item_id))
    conn.commit()
    conn.close()
    flash('Inventory updated!', 'success')
    return redirect(url_for('inventory'))

# Reports
@app.route('/reports')
@login_required
def reports():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    # Sales report
    c.execute("SELECT SUM(total) FROM orders WHERE status = 'completed'")
    total_sales = c.fetchone()[0] or 0
    # Table occupancy
    c.execute("SELECT COUNT(*) FROM tables WHERE status = 'occupied'")
    occupied_tables = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM tables")
    total_tables = c.fetchone()[0]
    # Low stock items
    c.execute("SELECT name, quantity, unit FROM inventory WHERE quantity <= low_stock_threshold")
    low_stock = c.fetchall()
    conn.close()
    return render_template('reports.html', total_sales=total_sales, occupied_tables=occupied_tables, total_tables=total_tables, low_stock=low_stock)

# Admin panel
@app.route('/admin')
@admin_required
def admin_panel():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM orders")
    total_orders = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM tables WHERE status = 'occupied'")
    occupied_tables = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM inventory WHERE quantity <= low_stock_threshold")
    low_stock_items = c.fetchone()[0]
    conn.close()
    return render_template('admin_panel.html', total_orders=total_orders, occupied_tables=occupied_tables, low_stock_items=low_stock_items)

# Manage menu items
@app.route('/menu', methods=['GET', 'POST'])
@admin_required
def menu_manage():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    if request.method == 'POST':
        name = request.form['name']
        price = request.form['price']
        description = request.form['description']
        image = request.files.get('image')
        image_path = None
        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_path = os.path.join('uploads', filename)
        if not name or not price:
            flash('Name and price are required.', 'error')
        else:
            c.execute("INSERT INTO menu_items (name, price, description, image_path) VALUES (?, ?, ?, ?)",
                      (name, price, description, image_path))
            conn.commit()
            flash('Menu item added!', 'success')
    c.execute("SELECT id, name, price, description, image_path FROM menu_items")
    menu_items = c.fetchall()
    conn.close()
    return render_template('menu_manage.html', menu_items=menu_items)

# Delete menu item
@app.route('/menu/delete/<int:item_id>')
@admin_required
def menu_delete(item_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT image_path FROM menu_items WHERE id = ?", (item_id,))
    image_path = c.fetchone()[0]
    if image_path:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(image_path)))
        except:
            pass
    c.execute("DELETE FROM menu_items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    flash('Menu item deleted!', 'success')
    return redirect(url_for('menu_manage'))

# Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email = ? AND password = ?", (email, hashed_password))
        user = c.fetchone()
        conn.close()
        if user:
            session['user_id'] = user[0]
            session['user_name'] = user[3]
            session['role'] = user[4]
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')

# Sign up
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']
        if not email or not password or not name:
            flash('All fields are required.', 'error')
        elif not is_valid_email(email):
            flash('Invalid email format.', 'error')
        elif len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
        else:
            hashed_password = hashlib.sha256(password.encode()).hexdigest()
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            try:
                c.execute("INSERT INTO users (email, password, name, role) VALUES (?, ?, ?, ?)",
                          (email, hashed_password, name, 'staff'))
                conn.commit()
                flash('Signup successful! Please log in.', 'success')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                flash('Email already exists.', 'error')
            conn.close()
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

if __name__ == '__main__':
    init_db()
    app.run(debug=True)