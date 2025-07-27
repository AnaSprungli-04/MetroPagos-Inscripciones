from flask import Flask, render_template, request, redirect, url_for, jsonify
import mercadopago
import os
import logging
import urllib.parse # Importar para codificar URLs

from dotenv import load_dotenv

load_dotenv() # Carga las variables del archivo .env

app = Flask(__name__)

# Configuración del logger para ver los mensajes en la consola
app.logger.setLevel(logging.INFO)

# --- CONFIGURACIÓN DE MERCADO PAGO ---
# ¡IMPORTANTE! Carga tus credenciales desde variables de entorno.
MERCADO_PAGO_ACCESS_TOKEN = os.environ.get("MERCADO_PAGO_ACCESS_TOKEN")
MERCADO_PAGO_PUBLIC_KEY = os.environ.get("MERCADO_PAGO_PUBLIC_KEY") # <-- AÑADIDO: Tu clave pública

# Validar que las credenciales se cargaron
if not MERCADO_PAGO_ACCESS_TOKEN or not MERCADO_PAGO_PUBLIC_KEY:
    app.logger.error("Error: Las credenciales de Mercado Pago (ACCESS_TOKEN y PUBLIC_KEY) no están configuradas en las variables de entorno.")
    # En un caso real, podrías querer detener la aplicación si las credenciales no están.
    # raise ValueError("Las credenciales de Mercado Pago no están configuradas.")

sdk = mercadopago.SDK(MERCADO_PAGO_ACCESS_TOKEN)

# --- CONSTANTES ---
GOOGLE_FORMS_COMPETIDORES_ID = "1FAIpQLSeA0tbwyKZ-u8zra-W6hlJL8TCTQOayqCpKwya3sON0ubS0nA" 
GOOGLE_FORMS_ENTRY_ID_NUM_OPERACION = "entry.1161481877"
GOOGLE_FORMS_ENTRY_ID_CLASE_BARCO = "entry.1553765108" 
GOOGLE_FORMS_ENTRENADORES_ID = "1FAIpQLSeZGar2xA3OR6SwNbKatSj1CLWQjRTmWyM0t-LOabpRWZYZ4g" 
URL_BASE = "https://metropolitanopagos-inscripciones.onrender.com" # Asegúrate que esta sea tu URL de producción

BASE_PRECIOS = {
    'entrenador': 0,
    'competidor': 0
}

PRECIOS_BARCOS = {
    'Optimist Principiantes': 70000,
    'Optimist Timoneles': 70000,
    'ILCA 7': 40000,
    'ILCA 6': 70000,
    'ILCA 4': 70000,
    '420': 120000,
    '29er': 120000
}

PRECIOS_BENEFICIO = {
    'Optimist Principiantes': 60000,
    'Optimist Timoneles': 60000,
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
    Procesa la inscripción. Para competidores, crea una preferencia de pago 
    y renderiza la página de pago embebido en lugar de redirigir.
    """
    rol = request.form.get('rol')
    mas_150km = request.form.get('mas_150km') == 'on'
    clase_barco = request.form.get('clase_barco')

    if rol == 'entrenador':
        google_forms_url = (
            f"https://docs.google.com/forms/d/e/{GOOGLE_FORMS_ENTRENADORES_ID}/viewform?usp=pp_url"
        )
        app.logger.info(f"Entrenador detectado. Redirigiendo a: {google_forms_url}")
        return redirect(google_forms_url)

    elif rol == 'competidor':
        if not clase_barco or clase_barco not in PRECIOS_BARCOS:
            app.logger.error("Competidor sin clase de barco o clase inválida.")
            return "Error: Por favor, selecciona una clase de barco válida.", 400

        total_price = PRECIOS_BARCOS[clase_barco]
        item_title = f"Inscripción Competidor - {clase_barco}"
        
        if mas_150km and clase_barco in PRECIOS_BENEFICIO:
            total_price = PRECIOS_BENEFICIO[clase_barco]
            item_title += " (Beneficio >150km)"
            app.logger.info(f"Aplicando beneficio para {clase_barco}. Nuevo precio: {total_price}")

        total_price = max(1, round(total_price, 2))
        app.logger.info(f"Precio final calculado para {clase_barco}: {total_price}")
        
        encoded_clase_barco = urllib.parse.quote_plus(clase_barco)
        
        preference_data = {
            "items": [{
                "title": item_title,
                "quantity": 1,
                "unit_price": float(total_price),
                "currency_id": "ARS" 
            }],
            "back_urls": {
                "success": f"{URL_BASE}/payment_success?clase_barco={encoded_clase_barco}", 
                "pending": f"{URL_BASE}/payment_pending?clase_barco={encoded_clase_barco}",
                "failure": f"{URL_BASE}/payment_failure?clase_barco={encoded_clase_barco}"
            },
            "auto_return": "approved", 
            "external_reference": f"METRO_{clase_barco or 'no_barco'}",
            "payment_methods": {
                "excluded_payment_types": [{"id": "ticket"}]
            }
        }

        try:
            preference_response = sdk.preference().create(preference_data)
            preference = preference_response.get("response")

            if not preference or preference_response.get("status") != 201:
                app.logger.error(f"Error en la respuesta de MP al crear preferencia: {preference_response}")
                return "Hubo un error al procesar el pago. Por favor, inténtalo de nuevo.", 500
            
            preference_id = preference['id']
            app.logger.info(f"Preferencia creada con ID: {preference_id}. Renderizando página de pago.")
            
            # --- CAMBIO PRINCIPAL: Renderizar la página de pago en lugar de redirigir ---
            return render_template(
                'payment_page.html',
                page_title="Completa tu Pago",
                public_key=MERCADO_PAGO_PUBLIC_KEY,
                preference_id=preference_id,
                item_title=item_title,
                total_price=total_price
            )
            # --------------------------------------------------------------------------
                
        except Exception as e:
            app.logger.error(f"Excepción al crear la preferencia de pago: {e}")
            return "Hubo un error inesperado al procesar tu solicitud de pago.", 500
    else:
        return "Error: Rol no válido seleccionado.", 400

# --- Las rutas /payment_success, /payment_pending, /payment_failure y el webhook se mantienen igual ---
# --- Son a donde Mercado Pago redirigirá al usuario DESPUÉS de completar el pago en tu página ---

@app.route('/payment_success')
def payment_success():
    payment_id = request.args.get('payment_id') 
    status = request.args.get('status') 
    clase_barco = request.args.get('clase_barco')
    
    app.logger.info(f"Pago exitoso. Payment ID: {payment_id}, Status: {status}, Clase Barco: {clase_barco}")

    google_forms_url_competidor = (
        f"https://docs.google.com/forms/d/e/{GOOGLE_FORMS_COMPETIDORES_ID}/viewform?"
        f"usp=pp_url&{GOOGLE_FORMS_ENTRY_ID_NUM_OPERACION}={payment_id}"
    )
    
    if clase_barco:
        encoded_clase_barco_for_form = urllib.parse.quote_plus(clase_barco)
        google_forms_url_competidor += f"&{GOOGLE_FORMS_ENTRY_ID_CLASE_BARCO}={encoded_clase_barco_for_form}"

    return render_template('success.html', 
                           page_title="¡Pago Exitoso!",
                           payment_id=payment_id, 
                           google_forms_url=google_forms_url_competidor)

@app.route('/payment_pending')
def payment_pending():
    app.logger.info(f"Pago pendiente recibido: {request.args}")
    return render_template('payment_status.html', status="pendiente", page_title="Pago Pendiente", message="Tu pago está pendiente de aprobación. Recibirás una notificación cuando se procese.")

@app.route('/payment_failure')
def payment_failure():
    app.logger.info(f"Pago fallido recibido: {request.args}")
    return render_template('payment_status.html', status="fallido", page_title="Pago Fallido", message="El pago no pudo ser procesado. Por favor, verifica los datos e intenta nuevamente.")

@app.route('/mercadopago-webhook', methods=['POST'])
def mercadopago_webhook():
    data = request.json 
    topic = data.get('topic') 
    resource_id = data.get('id') 
    app.logger.info(f"Webhook recibido. Topic: {topic}, ID: {resource_id}")

    if topic == 'payment':
        try:
            payment_info = sdk.payment().get(resource_id)
            if payment_info and payment_info["status"] == 200:
                payment = payment_info["response"]
                app.logger.info(f"Info del Webhook: Pago ID={payment['id']}, Estado={payment['status']}")
                # Aquí iría tu lógica para actualizar la base de datos
            else:
                app.logger.error(f"Error al obtener info del pago {resource_id} desde webhook: {payment_info}")
        except Exception as e:
            app.logger.error(f"Excepción en webhook de pago {resource_id}: {e}")
    
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    # Para producción, usa un servidor WSGI como Gunicorn y desactiva el modo debug
    app.run(debug=False, port=5001)