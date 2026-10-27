from flask import Flask, render_template, request, redirect, url_for, session
import mysql.connector
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'hotel_secreto_123'  # <-- NUEVO: Obligatorio para habilitar sesiones

db_config = {
    'host': 'hotel-bd-nube-ucb-8a79.k.aivencloud.com',
    'user': 'avnadmin',
    'password': 'AVNS_0QgU9AICY9rMVC9uz0m',
    'database': 'defaultdb',
    'port': 15881 # Reemplaza con el puerto exacto que te indique Aiven
}

# db_config = {
#    'host': 'localhost',
#    'user': 'root',
#    'password': '1234', 
#   'database': 'hotel_bd'
#}


@app.route('/')
def index():
    # <-- NUEVO: Si no hay usuario en sesión, lo mandamos al login
    if 'usuario' not in session:
        return redirect(url_for('login')) 
    
    habitaciones = []
    # ... (el resto de tu código del index queda exactamente igual) ...
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True) # dictionary=True nos devuelve los datos por nombre de columna
        
        # Consultamos las habitaciones y su tipo
        cursor.execute("""
            SELECT h.numero_habitacion, h.estado, t.nombre as tipo, t.precio_base 
            FROM Habitaciones h
            JOIN Tipo_Habitacion t ON h.id_tipohab = t.id_tipohab
            ORDER BY h.numero_habitacion ASC
        """)
        habitaciones = cursor.fetchall()
        
    except mysql.connector.Error as err:
        print(f"Error de conexión: {err}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    # Le pasamos la lista de habitaciones al HTML
    return render_template('index.html', habitaciones=habitaciones)


@app.route('/checkin/<int:numero_habitacion>', methods=['GET', 'POST'])
def checkin(numero_habitacion):
    if request.method == 'POST':
        # 1. Extraemos los datos que el usuario escribió en el formulario
        nombre = request.form['nombre']
        apellido = request.form['apellido']
        ci = request.form['ci']
        telefono = request.form['telefono']
        placa = request.form.get('placa', '')
        marca = request.form.get('marca', '')
        cat_vehiculo = request.form.get('cat_vehiculo', '')

        try:
            conn = mysql.connector.connect(**db_config)
            cursor = conn.cursor()

            # 2. Guardamos al huésped y obtenemos su ID generado
            cursor.execute("INSERT INTO Huespedes (nombre, apellido, ci, telefono) VALUES (%s, %s, %s, %s)", (nombre, apellido, ci, telefono))
            id_huesped = cursor.lastrowid

            # 3. Si ingresó una placa, guardamos el vehículo
            id_vehiculo = None
            if placa:
                cursor.execute("INSERT INTO Vehiculos (id_huesped, placa, marca, categoria) VALUES (%s, %s, %s, %s)", (id_huesped, placa, marca, cat_vehiculo))
                id_vehiculo = cursor.lastrowid

            # 4. Buscamos el ID interno de la habitación usando su número
            cursor.execute("SELECT id_habitacion FROM Habitaciones WHERE numero_habitacion = %s", (numero_habitacion,))
            id_habitacion = cursor.fetchone()[0]

            # 5. Creamos la Estancia (Registro)
            cursor.execute("INSERT INTO Registro_Estadia (id_huesped, id_habitacion, id_vehiculo) VALUES (%s, %s, %s)", (id_huesped, id_habitacion, id_vehiculo))

            # 6. Cambiamos el estado de la habitación a "Ocupada"
            cursor.execute("UPDATE Habitaciones SET estado = 'Ocupada' WHERE id_habitacion = %s", (id_habitacion,))

            # Confirmamos los cambios en la base de datos
            conn.commit()

        except mysql.connector.Error as err:
            print(f"Error en BD: {err}")
        finally:
            if 'conn' in locals() and conn.is_connected():
                cursor.close()
                conn.close()
        
        # Al terminar, lo devolvemos al panel principal
        return redirect(url_for('index'))

    # Si es GET (solo hizo clic en el botón), le mostramos la pantalla del formulario
    return render_template('checkin.html', numero_habitacion=numero_habitacion)

@app.route('/checkout/<int:numero_habitacion>', methods=['GET', 'POST'])
def checkout(numero_habitacion):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            # 1. Recibir todos los datos del formulario
            total_hab = float(request.form.get('total_habitacion', 0))
            total_parq = float(request.form.get('total_parqueo', 0))
            total_cons = float(request.form.get('total_consumos', 0))
            nit = request.form['nit']
            razon_social = request.form['razon_social']
            gran_total = total_hab + total_parq + total_cons

            # 2. Obtener el ID de habitación y registro activos
            cursor.execute("""
                SELECT h.id_habitacion, r.id_registro 
                FROM Habitaciones h
                JOIN Registro_Estadia r ON h.id_habitacion = r.id_habitacion
                WHERE h.numero_habitacion = %s AND r.fecha_salida IS NULL
            """, (numero_habitacion,))
            datos_activos = cursor.fetchone()
            
            id_habitacion = datos_activos['id_habitacion']
            id_registro = datos_activos['id_registro']

            # 3. Guardar la factura en la base de datos
            cursor.execute("""
                INSERT INTO Facturacion (id_registro, nit, razon_social, monto_habitacion, monto_parqueo, monto_consumos, monto_total)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (id_registro, nit, razon_social, total_hab, total_parq, total_cons, gran_total))

            # 4. Cerrar la estancia del huésped
            cursor.execute("""
                UPDATE Registro_Estadia 
                SET fecha_salida = CURRENT_TIMESTAMP,
                    monto_habitacion = %s,
                    precio_parqueo_aplicado = %s
                WHERE id_registro = %s
            """, (total_hab, total_parq, id_registro))

            # 5. Pasar la habitación a limpieza
            cursor.execute("UPDATE Habitaciones SET estado = 'Limpieza' WHERE id_habitacion = %s", (id_habitacion,))
            
            conn.commit()
            return redirect(url_for('index'))

        # === LÓGICA PARA EL MÉTODO GET (Mostrar la pantalla de Check-out) ===
        cursor.execute("""
            SELECT h.numero_habitacion, t.precio_base, hu.nombre, hu.apellido, hu.ci, 
                   r.fecha_ingreso, v.categoria as categoria_vehiculo, r.id_registro
            FROM Habitaciones h
            JOIN Tipo_Habitacion t ON h.id_tipohab = t.id_tipohab
            JOIN Registro_Estadia r ON h.id_habitacion = r.id_habitacion
            JOIN Huespedes hu ON r.id_huesped = hu.id_huesped
            LEFT JOIN Vehiculos v ON r.id_vehiculo = v.id_vehiculo
            WHERE h.numero_habitacion = %s AND r.fecha_salida IS NULL
        """, (numero_habitacion,))
        
        datos_estancia = cursor.fetchone()
        
        if datos_estancia:
            id_registro = datos_estancia['id_registro']

            # Calcular Días
            fecha_ingreso = datos_estancia['fecha_ingreso']
            diferencia = datetime.now() - fecha_ingreso
            dias = diferencia.days if diferencia.days >= 1 else 1

            # Calcular Habitación y Parqueo
            precio_base = float(datos_estancia['precio_base'])
            total_habitacion = precio_base * dias

            precio_parqueo = 0.0
            cat_vehiculo = datos_estancia['categoria_vehiculo']
            if cat_vehiculo == 'Pequeño/Mediano':
                precio_parqueo = 5.0
            elif cat_vehiculo == 'Grande':
                precio_parqueo = 10.0
            total_parqueo = precio_parqueo * dias

            # Buscar consumos
            cursor.execute("""
                SELECT SUM(cantidad * precio_unitario_historico) as total_consumos 
                FROM Consumos_Detalles 
                WHERE id_registro = %s
            """, (id_registro,))
            res_consumos = cursor.fetchone()
            total_consumos = float(res_consumos['total_consumos'] or 0.0)

            cursor.execute("""
                SELECT p.nombre_producto, c.cantidad, (c.cantidad * c.precio_unitario_historico) as subtotal
                FROM Consumos_Detalles c
                JOIN Productos p ON c.id_producto = p.id_producto
                WHERE c.id_registro = %s
            """, (id_registro,))
            lista_consumos = cursor.fetchall()

            gran_total = total_habitacion + total_parqueo + total_consumos

            datos_estancia['nombre_completo'] = f"{datos_estancia['nombre']} {datos_estancia['apellido']}"
            datos_estancia['dias'] = dias
            datos_estancia['total_habitacion'] = total_habitacion
            datos_estancia['precio_parqueo'] = precio_parqueo
            datos_estancia['total_parqueo'] = total_parqueo
            datos_estancia['total_consumos'] = total_consumos
            datos_estancia['lista_consumos'] = lista_consumos
            datos_estancia['gran_total'] = gran_total

    except mysql.connector.Error as err:
        print(f"Error en BD: {err}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template('checkout.html', datos=datos_estancia)

@app.route('/consumo/<int:numero_habitacion>', methods=['GET', 'POST'])
def consumo(numero_habitacion):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        # 1. Buscar el id_registro de la estancia activa en esta habitación
        cursor.execute("""
            SELECT r.id_registro 
            FROM Habitaciones h
            JOIN Registro_Estadia r ON h.id_habitacion = r.id_habitacion
            WHERE h.numero_habitacion = %s AND r.fecha_salida IS NULL
        """, (numero_habitacion,))
        registro_activo = cursor.fetchone()

        if not registro_activo:
            return redirect(url_for('index')) # Si no hay nadie, lo devolvemos al inicio
            
        id_registro = registro_activo['id_registro']

        if request.method == 'POST':
            id_producto = request.form['id_producto']
            cantidad = int(request.form['cantidad'])

            # Extraemos el precio actual del producto para congelarlo en el historial
            cursor.execute("SELECT precio_venta FROM Productos WHERE id_producto = %s", (id_producto,))
            precio_unitario = cursor.fetchone()['precio_venta']

            # Guardamos el detalle del consumo
            cursor.execute("""
                INSERT INTO Consumos_Detalles (id_registro, id_producto, cantidad, precio_unitario_historico)
                VALUES (%s, %s, %s, %s)
            """, (id_registro, id_producto, cantidad, precio_unitario))

            # Descontamos el stock
            cursor.execute("UPDATE Productos SET stock_actual = stock_actual - %s WHERE id_producto = %s", (cantidad, id_producto))
            
            conn.commit()
            return redirect(url_for('index'))

        # Si es GET: Buscamos los productos para llenar el desplegable del HTML
        cursor.execute("SELECT id_producto, nombre_producto, precio_venta FROM Productos WHERE stock_actual > 0")
        lista_productos = cursor.fetchall()

    except mysql.connector.Error as err:
        print(f"Error en BD: {err}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template('consumo.html', numero_habitacion=numero_habitacion, productos=lista_productos)

@app.route('/limpiar/<int:numero_habitacion>')
def limpiar_habitacion(numero_habitacion):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        
        # Cambiamos el estado de Limpieza a Disponible
        cursor.execute("UPDATE Habitaciones SET estado = 'Disponible' WHERE numero_habitacion = %s", (numero_habitacion,))
        conn.commit()
        
    except mysql.connector.Error as err:
        print(f"Error en BD: {err}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
            
    return redirect(url_for('index'))

@app.route('/facturacion')
def facturacion():
    # Proteger la ruta
    if 'usuario' not in session:
        return redirect(url_for('login'))
        
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # 1. Tabla de facturas detalladas
        cursor.execute("""
            SELECT f.nit, f.razon_social, f.monto_total, r.fecha_salida, h.numero_habitacion
            FROM Facturacion f
            JOIN Registro_Estadia r ON f.id_registro = r.id_registro
            JOIN Habitaciones h ON r.id_habitacion = h.id_habitacion
            ORDER BY r.fecha_salida DESC
        """)
        lista_facturas = cursor.fetchall()
        total_recaudado = sum(float(fac['monto_total']) for fac in lista_facturas)

        # 2. NUEVO: Agrupar ingresos por fecha para el gráfico
        cursor.execute("""
            SELECT DATE(r.fecha_salida) as fecha, SUM(f.monto_total) as total_dia
            FROM Facturacion f
            JOIN Registro_Estadia r ON f.id_registro = r.id_registro
            GROUP BY DATE(r.fecha_salida)
            ORDER BY DATE(r.fecha_salida) ASC
            LIMIT 7
        """)
        ventas_por_dia = cursor.fetchall()
        
        # Separar los datos en dos listas para dárselas al gráfico HTML
        fechas_chart = [str(v['fecha']) for v in ventas_por_dia]
        totales_chart = [float(v['total_dia']) for v in ventas_por_dia]
        
    except mysql.connector.Error as err:
        print(f"Error en BD: {err}")
        lista_facturas = []
        total_recaudado = 0
        fechas_chart = []
        totales_chart = []
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
            
    # Le enviamos las listas del gráfico al HTML
    return render_template('facturacion.html', 
                           facturas=lista_facturas, 
                           total_recaudado=total_recaudado,
                           fechas_chart=fechas_chart,
                           totales_chart=totales_chart)


@app.route('/corte_caja', methods=['GET', 'POST'])
def corte_caja():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            monto_calculado = float(request.form.get('monto_calculado', 0))
            
            # 1. Buscamos el ID interno del usuario que está en sesión
            cursor.execute("SELECT id_usuario FROM Usuarios WHERE user = %s", (session['usuario'],))
            user_data = cursor.fetchone()
            id_usuario = user_data['id_usuario'] if user_data else 1
            
            # 2. Guardamos el registro del corte
            cursor.execute("""
                INSERT INTO Cortes_Caja (id_usuario, monto_calculado) 
                VALUES (%s, %s)
            """, (id_usuario, monto_calculado))
            
            conn.commit()
            # Podríamos redirigir a un mensaje de éxito, por ahora volvemos al inicio
            return redirect(url_for('index'))

        # === LÓGICA GET: Calcular ingresos del día actual ===
        # Sumamos las facturas cuya fecha de salida coincida con hoy (CURDATE)
        cursor.execute("""
            SELECT SUM(f.monto_total) as total_hoy
            FROM Facturacion f
            JOIN Registro_Estadia r ON f.id_registro = r.id_registro
            WHERE DATE(r.fecha_salida) = CURDATE()
        """)
        resultado = cursor.fetchone()
        
        # Si no hay ventas hoy, resultado['total_hoy'] será None, lo pasamos a 0.0
        total_hoy = float(resultado['total_hoy'] or 0.0)

    except mysql.connector.Error as err:
        print(f"Error en BD: {err}")
        total_hoy = 0.0
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

    return render_template('corte_caja.html', total_hoy=total_hoy)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        usuario = request.form['usuario']
        password = request.form['password']
        
        try:
            conn = mysql.connector.connect(**db_config)
            cursor = conn.cursor(dictionary=True)
            # Buscamos si el usuario y la contraseña coinciden en la base de datos
            cursor.execute("SELECT * FROM Usuarios WHERE user = %s AND pass = %s", (usuario, password))
            user_data = cursor.fetchone()
            
            if user_data:
                # Si existe, guardamos su nombre en la sesión y lo dejamos entrar
                session['usuario'] = user_data['user']
                session['nombre'] = user_data['nombre']
                return redirect(url_for('index'))
            else:
                error = "Usuario o contraseña incorrectos."
                
        except mysql.connector.Error as err:
            print(f"Error en BD: {err}")
        finally:
            if 'conn' in locals() and conn.is_connected():
                cursor.close()
                conn.close()
                
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear() # Borramos los datos de la sesión
    return redirect(url_for('login'))

@app.route('/usuarios', methods=['GET', 'POST'])
def usuarios():
    if 'usuario' not in session:
        return redirect(url_for('login'))
        
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # Si envían el formulario, insertamos el nuevo usuario
        if request.method == 'POST':
            ci = request.form['ci_usuario']
            nom = request.form['nombre']
            ape = request.form['apellido']
            usr = request.form['user']
            pwd = request.form['pass']
            tipo = request.form['tipo']
            
            cursor.execute("""
                INSERT INTO Usuarios (ci_usuario, nombre, apellido, user, pass, tipo) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (ci, nom, ape, usr, pwd, tipo))
            conn.commit()
            return redirect(url_for('usuarios'))
            
        # Si es GET, traemos la lista de todos los usuarios
        cursor.execute("SELECT id_usuario, ci_usuario, nombre, apellido, user, tipo FROM Usuarios")
        lista_usuarios = cursor.fetchall()
        
    except mysql.connector.Error as err:
        print(f"Error en BD: {err}")
        lista_usuarios = []
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
            
    return render_template('usuarios.html', usuarios=lista_usuarios)

@app.route('/eliminar_usuario/<int:id_usuario>')
def eliminar_usuario(id_usuario):
    if 'usuario' not in session:
        return redirect(url_for('login'))
        
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Usuarios WHERE id_usuario = %s", (id_usuario,))
        conn.commit()
    except mysql.connector.Error as err:
        print(f"Error en BD: {err}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
            
    return redirect(url_for('usuarios'))

@app.route('/huespedes', methods=['GET', 'POST'])
def buscador_huespedes():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    huesped = None
    historial = []
    post_request = False

    if request.method == 'POST':
        post_request = True
        ci_buscado = request.form['ci_buscado']

        try:
            conn = mysql.connector.connect(**db_config)
            cursor = conn.cursor(dictionary=True)

            # 1. Buscar los datos personales del huésped
            cursor.execute("SELECT * FROM Huespedes WHERE ci = %s", (ci_buscado,))
            huesped = cursor.fetchone()

            # 2. Si el huésped existe, buscar todas las veces que se hospedó
            if huesped:
                cursor.execute("""
                    SELECT r.fecha_ingreso, r.fecha_salida, h.numero_habitacion, f.monto_total
                    FROM Registro_Estadia r
                    JOIN Habitaciones h ON r.id_habitacion = h.id_habitacion
                    LEFT JOIN Facturacion f ON r.id_registro = f.id_registro
                    WHERE r.id_huesped = %s
                    ORDER BY r.fecha_ingreso DESC
                """, (huesped['id_huesped'],))
                historial = cursor.fetchall()

        except mysql.connector.Error as err:
            print(f"Error en BD: {err}")
        finally:
            if 'conn' in locals() and conn.is_connected():
                cursor.close()
                conn.close()

    return render_template('huespedes.html', huesped=huesped, historial=historial, post_request=post_request)

if __name__ == '__main__':
    app.run(debug=True)