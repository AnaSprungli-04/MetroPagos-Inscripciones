from flask import Flask, render_template, request, redirect, url_for, jsonify
import mercadopago
import os
import logging # Importar el módulo de logging

app = Flask(__name__)

# Configuración del logger para ver los mensajes en la consola
app.logger.setLevel(logging.INFO)

# --- CONFIGURACIÓN DE MERCADO PAGO ---
# ¡IMPORTANTE! Reemplaza con tu Access Token REAL DE PRUEBA o de PRODUCCIÓN
# Mantenlo seguro, no lo expongas en el frontend
MERCADO_PAGO_ACCESS_TOKEN = "TEST-7537326222958564-081218-6f78e1f990e1b269a602202189d4f203-1123457005"
sdk = mercadopago.SDK(MERCADO_PAGO_ACCESS_TOKEN)

# --- ID DEL GOOGLE FORMS PARA COMPETIDORES Y SU CAMPO DE NÚMERO DE OPERACIÓN ---
# ¡Reemplaza con el ID real de tu Google Forms para COMPETIDORES!
GOOGLE_FORMS_COMPETIDORES_ID = "1FAIpQLSeA0tbwyKZ-u8zra-W6hlJL8TCTQOayqCpKwya3sON0nA" # EJEMPLO: REEMPLAZA
# Este ID es para el campo "Número de Operación" en el form de COMPETIDORES
GOOGLE_FORMS_ENTRY_ID_NUM_OPERACION = "entry.1161481877"

# --- ID DEL GOOGLE FORMS PARA ENTRENADORES ---
# ¡Reemplaza con el ID real de tu NUEVO Google Forms para ENTRENADORES!
GOOGLE_FORMS_ENTRENADORES_ID = "1FAIpQLSd1sYDAiCHkwzRxzJy2nRRQptRDumRrke7iMFOLSZjpPsjCaQ" # <-- ¡REEMPLAZA ESTO!

# --- URL BASE PARA PRUEBAS LOCALES (CAMBIAR PARA PRODUCCIÓN) ---
# ¡IMPORTANTE! Para que 'auto_return' funcione correctamente, Mercado Pago
# REQUIERE que las back_urls sean accesibles y, en la mayoría de los casos, HTTPS.
# El error "auto_return invalid. back_url.success must be defined" a menudo significa
# que la URL local (http://127.0.0.1) no es considerada válida por Mercado Pago
# cuando 'auto_return' está activo.
#
# Para pruebas locales con 'auto_return':
# 1. Usa `ngrok` (https://ngrok.com/) para exponer tu localhost con HTTPS.
#    Ejecuta: `ngrok http 5000` y copia la URL HTTPS que te dé (ej. "https://<tu_subdominio>.ngrok-free.app").
# 2. REEMPLAZA el valor de URL_BASE con esa URL de ngrok.
#
# Para producción:
# 1. Reemplaza con tu dominio HTTPS real (ej. "https://tudominio.com").
URL_BASE = "https://metropolitanopagos-inscripciones.onrender.com" # Para pruebas locales SIN auto_return, o si usas ngrok y lo actualizas.

# --- LÓGICA DE PRECIOS ---
BASE_PRECIOS = {
    'entrenador': 0,
    'competidor': 20
}

PRECIOS_BARCOS = {
    'Optimist Principiantes': 10,
    'Optimist Timoneles': 10,
    'ILCA 7': 20,
    'ILCA 6': 20,
    'ILCA 4': 20,
    '420': 15,
    '29er': 15
}

BENEFICIO_DISTANCIA_PORCENTAJE = 0.10 # 10% de descuento

# --- RUTAS DE LA APLICACIÓN ---

@app.route('/')
def index():
    """Renderiza la página principal con el formulario de inscripción."""
    return render_template('index.html', page_title="Inscripción al Evento")

@app.route('/process_inscription', methods=['POST'])
def process_inscription():
    """
    Recibe los datos del formulario HTML.
    Si es entrenador, redirige directamente al Google Form de entrenadores.
    Si es competidor, calcula el precio y redirige a Mercado Pago.
    """
    rol = request.form.get('rol')
    mas_150km = request.form.get('mas_150km') == 'on'
    clase_barco = request.form.get('clase_barco')

    if rol == 'entrenador':
        # Los entrenadores van directo a su formulario específico
        # Aquí NO necesitamos un 'payment_id' porque no hay pago asociado directamente desde Mercado Pago
        google_forms_url = (
            f"https://docs.google.com/forms/d/e/{GOOGLE_FORMS_ENTRENADORES_ID}/viewform?"
            f"usp=pp_url" # Solo la URL base del form de entrenadores
            # Si el form de entrenadores tuviera algún campo para un "ID de transacción" ficticio, lo agregarías aquí
            # f"&entry.XYZABCDE=ENTRENADOR_NO_PAGA"
        )
        app.logger.info(f"Entrenador detectado. Redirigiendo a su formulario específico: {google_forms_url}")
        return redirect(google_forms_url)

    elif rol == 'competidor':
        total_price = BASE_PRECIOS['competidor']
        item_title = "Inscripción Competidor"
        
        if clase_barco and clase_barco in PRECIOS_BARCOS:
            total_price += PRECIOS_BARCOS[clase_barco]
            item_title += f" - {clase_barco}"
        else:
            app.logger.error("Competidor sin clase de barco o clase de barco inválida.")
            return "Error: Por favor, selecciona tu clase de barco.", 400

        if mas_150km:
            total_price -= (total_price * BENEFICIO_DISTANCIA_PORCENTAJE)
            item_title += " (Beneficio >150km)"

        # Asegura que el precio mínimo sea 1 (Mercado Pago requiere un precio mínimo)
        total_price = max(1, round(total_price, 2))

        app.logger.info(f"Calculando precio para competidor: Rol={rol}, >150km={mas_150km}, Barco={clase_barco} -> Precio Final={total_price}")

        preference_data = {
            "items": [
                {
                    "title": item_title,
                    "quantity": 1,
                    "unit_price": float(total_price),
                    "currency_id": "ARS" # Es buena práctica especificar la moneda aquí también
                }
            ],
            # Las URLs de retorno de Mercado Pago a tu aplicación
            "back_urls": {
                "success": f"{URL_BASE}/payment_success", # Redirige a tu ruta /payment_success
                "pending": f"{URL_BASE}/payment_pending",
                "failure": f"{URL_BASE}/payment_failure"
            },
            # Este parámetro es crucial para la redirección automática.
            # Si estás en localhost y tienes problemas (como el error 400),
            # es muy probable que debas usar ngrok (o similar) para exponer
            # tu URL_BASE con HTTPS.
            "auto_return": "approved", # Redirige automáticamente solo si el pago es aprobado
            # Referencia externa para identificar la transacción en tu sistema
            "external_reference": f"inscripcion_comp_{clase_barco or 'no_barco'}_{os.urandom(8).hex()}"
        }

        try:
            preference_response = sdk.preference().create(preference_data)
            preference = preference_response["response"]
            
            if preference_response["status"] == 201: # 201 Created es el código de éxito
                init_point = preference["init_point"]
                app.logger.info(f"Preferencia creada exitosamente. Redirigiendo a: {init_point}")
                return redirect(init_point)
            else:
                app.logger.error(f"Error al crear la preferencia de pago: {preference_response['status']} - {preference_response['response']}")
                return "Hubo un error al procesar el pago. Por favor, inténtalo de nuevo más tarde."
                
        except Exception as e:
            app.logger.error(f"Excepción al crear la preferencia de pago: {e}")
            return "Hubo un error inesperado al procesar tu solicitud de pago."
    else:
        return "Error: Rol no válido seleccionado.", 400

@app.route('/payment_success')
def payment_success():
    """
    Esta es la página a la que Mercado Pago redirige tras un pago exitoso.
    Aquí se captura el 'payment_id' y se usa para construir la URL del Google Forms.
    Luego, el template 'success.html' usará JavaScript para la redirección final.
    """
    payment_id = request.args.get('payment_id') # Captura el payment_id de la URL de Mercado Pago
    status = request.args.get('status') # Captura el status (ej. "approved")
    collection_id = request.args.get('collection_id') # Otro ID importante
    
    app.logger.info(f"Redirección de éxito de MP recibida. Payment ID: {payment_id}, Status: {status}, Collection ID: {collection_id}")

    # Construye la URL del Google Forms para competidores, inyectando el payment_id
    google_forms_url_competidor = (
        f"https://docs.google.com/forms/d/e/{GOOGLE_FORMS_COMPETIDORES_ID}/viewform?"
        f"usp=pp_url&{GOOGLE_FORMS_ENTRY_ID_NUM_OPERACION}={payment_id}"
    )
    
    return render_template('success.html', 
                           message="¡Tu pago fue procesado con éxito! Por favor, verifica tu correo o continúa con los pasos adicionales.", 
                           payment_id=payment_id, 
                           google_forms_url=google_forms_url_competidor)

@app.route('/payment_pending')
def payment_pending():
    """Maneja la redirección para pagos pendientes."""
    payment_id = request.args.get('payment_id')
    status = request.args.get('status')
    app.logger.info(f"Redirección de pendiente de MP recibida. Payment ID: {payment_id}, Status: {status}")
    return render_template('payment_status.html', status="pendiente", message="Tu pago está pendiente de aprobación. Por favor, revisa el estado de tu pago en Mercado Pago.")

@app.route('/payment_failure')
def payment_failure():
    """Maneja la redirección para pagos fallidos."""
    payment_id = request.args.get('payment_id')
    status = request.args.get('status')
    app.logger.info(f"Redirección de fallo de MP recibida. Payment ID: {payment_id}, Status: {status}")
    return render_template('payment_status.html', status="fallido", message="Tu pago no pudo ser procesado. Por favor, verifica tus datos o intenta con otro método de pago.")

@app.route('/mercadopago-webhook', methods=['POST'])
def mercadopago_webhook():
    """
    Endpoint para recibir notificaciones de Webhook de Mercado Pago.
    ¡ESTO ES CRÍTICO PARA LA FIABILIDAD!
    """
    data = request.json # Los webhooks de MP envían JSON
    
    # Es crucial validar que la solicitud proviene de Mercado Pago.
    # Puedes verificar la firma o la IP de origen si necesitas mayor seguridad.
    
    topic = data.get('topic') # Tipo de evento (ej. 'payment', 'merchant_order')
    resource_id = data.get('id') # ID del recurso asociado al evento (ej. ID de pago)

    app.logger.info(f"Webhook recibido. Topic: {topic}, Resource ID: {resource_id}")

    if topic == 'payment':
        try:
            # Obtener los detalles completos del pago usando el SDK
            payment_info = sdk.payment().get(resource_id)
            
            if payment_info and payment_info["status"] == 200:
                payment = payment_info["response"]
                payment_id = payment["id"]
                payment_status = payment["status"]
                external_reference = payment.get("external_reference")

                app.logger.info(f"Detalles del pago del Webhook: ID={payment_id}, Estado={payment_status}, Ref. Externa={external_reference}")

                # --- AQUÍ ES DONDE ACTUALIZARÍAS TU BASE DE DATOS ---
                # Dependiendo del 'payment_status' ('approved', 'pending', 'rejected', etc.)
                # actualiza el estado de la inscripción en tu sistema.
                if payment_status == 'approved':
                    app.logger.info(f"Pago {payment_id} APROBADO. Actualizando estado de inscripción para {external_reference}.")
                    # Lógica para marcar la inscripción como pagada en tu DB
                elif payment_status == 'pending':
                    app.logger.info(f"Pago {payment_id} PENDIENTE. Actualizando estado de inscripción para {external_reference}.")
                    # Lógica para marcar la inscripción como pendiente en tu DB
                elif payment_status == 'rejected':
                    app.logger.info(f"Pago {payment_id} RECHAZADO. Actualizando estado de inscripción para {external_reference}.")
                    # Lógica para marcar la inscripción como rechazada en tu DB
                # ... manejar otros estados ...

            else:
                app.logger.error(f"Error al obtener detalles del pago {resource_id} desde el webhook: {payment_info}")

        except Exception as e:
            app.logger.error(f"Excepción al procesar webhook de pago {resource_id}: {e}")
    
    # Siempre devuelve un 200 OK a Mercado Pago para confirmar que recibiste la notificación
    return jsonify({"status": "ok"}), 200

# --- INICIAR EL SERVIDOR FLASK ---
if __name__ == '__main__':
    # Para producción, desactiva debug=True y usa un servidor WSGI como Gunicorn
    app.run(debug=True, port=5000)
