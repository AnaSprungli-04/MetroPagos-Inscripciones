from flask import Flask, render_template, request, redirect, url_for, jsonify
import mercadopago
import os
import logging
import urllib.parse # Importar para codificar URLs

from dotenv import load_dotenv

load_dotenv() # Carga las variables del archivo .env
# ... el resto de tu código
app = Flask(__name__)

# Configuración del logger para ver los mensajes en la consola
app.logger.setLevel(logging.INFO)

# --- CONFIGURACIÓN DE MERCADO PAGO ---
# ¡IMPORTANTE! En producción, carga esto desde una variable de entorno por seguridad.
# NO lo dejes harcodeado en el código fuente de tu repositorio público.
MERCADO_PAGO_ACCESS_TOKEN = os.environ.get("MERCADO_PAGO_ACCESS_TOKEN")
sdk = mercadopago.SDK(MERCADO_PAGO_ACCESS_TOKEN)

app.logger.info(f"DEBBUGING: {MERCADO_PAGO_ACCESS_TOKEN[:10]}")

# MERCADO_PAGO_ACCESS_TOKEN = os.environ.get("MERCADO_PAGO_ACCESS_TOKEN", "TEST-7537326222958564-081218-6f78e1f990e1b269a602202189d4f203-1123457005")

GOOGLE_FORMS_COMPETIDORES_ID = "1FAIpQLSeA0tbwyKZ-u8zra-W6hlJL8TCTQOayqCpKwya3sON0ubS0nA" 
GOOGLE_FORMS_ENTRY_ID_NUM_OPERACION = "entry.1161481877"
GOOGLE_FORMS_ENTRY_ID_CLASE_BARCO = "entry.1553765108" 
GOOGLE_FORMS_ENTRENADORES_ID = "1FAIpQLSeZGar2xA3OR6SwNbKatSj1CLWQjRTmWyM0t-LOabpRWZYZ4g" 
URL_BASE = "https://metropolitanopagos-inscripciones.onrender.com" 


BASE_PRECIOS = {
    'entrenador': 0,
    'competidor': 0
}

PRECIOS_BARCOS = {
    #'Optimist Principiantes': 70000,
    #'Optimist Timoneles': 70000,
    #'Sudamericano - Optimist Timoneles': 40000,
    'ILCA 7': 40000,
    #'ILCA 6': 70000,
    #'ILCA 4': 70000,
    #'420': 120000,
    #'29er': 120000
}

# --- NUEVOS PRECIOS DE BENEFICIO FIJO POR CLASE DE BARCO ---
PRECIOS_BENEFICIO = {
    'Optimist Principiantes': 60000,
    'Optimist Timoneles': 60000,
    'Sudamericano - Optimist Timoneles': 40000,
    'ILCA 7': 35000,
    'ILCA 6': 60000,
    'ILCA 4': 60000,
    '420': 100000,
    '29er': 100000
}


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
    clase_barco = request.form.get('clase_barco') # Capturamos la clase_barco

    if rol == 'entrenador':
        # Los entrenadores van directo a su formulario específico
        google_forms_url = (
            f"https://docs.google.com/forms/d/e/{GOOGLE_FORMS_ENTRENADORES_ID}/viewform?"
            f"usp=pp_url"
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

        # --- LÓGICA PARA EL BENEFICIO FIJO ---
        if mas_150km:
            if clase_barco in PRECIOS_BENEFICIO:
                total_price = PRECIOS_BENEFICIO[clase_barco]
                item_title += " (Beneficio >150km)"
                app.logger.info(f"Aplicando beneficio fijo de {PRECIOS_BENEFICIO[clase_barco]} para {clase_barco}.")
            else:
                app.logger.warning(f"Clase de barco '{clase_barco}' no tiene un beneficio fijo definido, no se aplicará descuento por distancia.")
        # --- FIN LÓGICA PARA EL BENEFICIO FIJO ---

        total_price = max(1, round(total_price, 2))

        app.logger.info(f"Calculando precio para competidor: Rol={rol}, >150km={mas_150km}, Barco={clase_barco} -> Precio Final={total_price}")

        # Codificar la clase_barco para URL
        encoded_clase_barco = urllib.parse.quote_plus(clase_barco)

        preference_data = {
            "items": [
                {
                    "title": item_title,
                    "quantity": 1,
                    "unit_price": float(total_price),
                    "currency_id": "ARS" 
                }
            ],
            "back_urls": {
                # Añadir clase_barco como parámetro a las URLs de retorno
                "success": f"{URL_BASE}/payment_success?clase_barco={encoded_clase_barco}", 
                "pending": f"{URL_BASE}/payment_pending?clase_barco={encoded_clase_barco}",
                "failure": f"{URL_BASE}/payment_failure?clase_barco={encoded_clase_barco}"
            },
            "auto_return": "approved", 
            "external_reference": f"METRO_{clase_barco or 'no_barco'}",
             "payment_methods": {
                "excluded_payment_types": [
                    {"id": "ticket"} # Excluye pagos en efectivo (ticket)
                ]
            }

        }

        try:
            preference_response = sdk.preference().create(preference_data)
            preference = preference_response["response"]

            if preference_response["status"] == 201: 
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
    Aquí se captura el 'payment_id' y la 'clase_barco' y se usan para construir la URL del Google Forms.
    Luego, el template 'success.html' usará JavaScript para la redirección final.
    """
    payment_id = request.args.get('payment_id') 
    status = request.args.get('status') 
    collection_id = request.args.get('collection_id') 
    clase_barco = request.args.get('clase_barco')

    app.logger.info(f"Redirección de éxito de MP recibida. Payment ID: {payment_id}, Status: {status}, Collection ID: {collection_id}, Clase Barco: {clase_barco}")

    # Construye la URL del Google Forms para competidores, inyectando el payment_id
    google_forms_url_competidor = (
        f"https://docs.google.com/forms/d/e/{GOOGLE_FORMS_COMPETIDORES_ID}/viewform?"
        f"usp=pp_url&{GOOGLE_FORMS_ENTRY_ID_NUM_OPERACION}={payment_id}"
    )

    # Si tenemos la clase de barco, la añadimos a la URL del Google Forms
    if clase_barco:
        # Codificar la clase_barco para URL antes de añadirla al Google Forms
        encoded_clase_barco_for_form = urllib.parse.quote_plus(clase_barco)
        google_forms_url_competidor += f"&{GOOGLE_FORMS_ENTRY_ID_CLASE_BARCO}={encoded_clase_barco_for_form}"

    return render_template('success.html', 
                           message="¡Tu pago fue procesado con éxito! Por favor, verifica tu correo o continúa con los pasos adicionales.", 
                           payment_id=payment_id, 
                           google_forms_url=google_forms_url_competidor)

@app.route('/payment_pending')
def payment_pending():
    """Maneja la redirección para pagos pendientes."""
    payment_id = request.args.get('payment_id')
    status = request.args.get('status')
    clase_barco = request.args.get('clase_barco') # Recuperamos la clase_barco
    app.logger.info(f"Redirección de pendiente de MP recibida. Payment ID: {payment_id}, Status: {status}, Clase Barco: {clase_barco}")
    return render_template('payment_status.html', status="pendiente", message="Tu pago está pendiente de aprobación. Por favor, revisa el estado de tu pago en Mercado Pago.")

@app.route('/payment_failure')
def payment_failure():
    """Maneja la redirección para pagos fallidos."""
    payment_id = request.args.get('payment_id')
    status = request.args.get('status')
    clase_barco = request.args.get('clase_barco') # Recuperamos la clase_barco
    app.logger.info(f"Redirección de fallo de MP recibida. Payment ID: {payment_id}, Status: {status}, Clase Barco: {clase_barco}")
    return render_template('payment_status.html', status="fallido", message="Tu pago no pudo ser procesado. Por favor, verifica tus datos o intenta con otro método de pago.")

@app.route('/mercadopago-webhook', methods=['POST'])
def mercadopago_webhook():
    """
    Endpoint para recibir notificaciones de Webhook de Mercado Pago.
    ¡ESTO ES CRÍTICO PARA LA FIABILIDAD!
    """
    data = request.json 

    # Es crucial validar que la solicitud proviene de Mercado Pago.
    # Puedes verificar la firma o la IP de origen si necesitas mayor seguridad.

    topic = data.get('topic') 
    resource_id = data.get('id') 

    app.logger.info(f"Webhook recibido. Topic: {topic}, Resource ID: {resource_id}")

    if topic == 'payment':
        try:
            payment_info = sdk.payment().get(resource_id)

            if payment_info and payment_info["status"] == 200:
                payment = payment_info["response"]
                payment_id = payment["id"]
                payment_status = payment["status"]
                external_reference = payment.get("external_reference")

                app.logger.info(f"Detalles del pago del Webhook: ID={payment_id}, Estado={payment_status}, Ref. Externa={external_reference}")

                # --- AQUÍ ES DONDE ACTUALIZARÍAS TU BASE DE DATOS ---
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
    app.run(debug=False, port=5000)