from flask import Flask, render_template, request, redirect, url_for, jsonify
import mercadopago
import os
import logging
import urllib.parse

from dotenv import load_dotenv

load_dotenv() # Carga las variables del archivo .env

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# --- CONFIGURACIÓN DE MERCADO PAGO ---
MERCADO_PAGO_ACCESS_TOKEN = os.environ.get("MERCADO_PAGO_ACCESS_TOKEN")
MERCADO_PAGO_PUBLIC_KEY = os.environ.get("MERCADO_PAGO_PUBLIC_KEY") # <-- NUEVA CLAVE PÚBLICA
sdk = mercadopago.SDK(MERCADO_PAGO_ACCESS_TOKEN)

app.logger.info(f"Access Token Cargado: {MERCADO_PAGO_ACCESS_TOKEN[:10]}...")
app.logger.info(f"Public Key Cargada: {MERCADO_PAGO_PUBLIC_KEY[:10]}...")


# --- TUS CONSTANTES (SIN CAMBIOS) ---
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
    (MODIFICADO)
    Recibe los datos del formulario.
    Si es entrenador, redirige al Form.
    Si es competidor, calcula el precio y renderiza la página de pago embebido.
    """
    rol = request.form.get('rol')
    mas_150km = request.form.get('mas_150km') == 'on'
    clase_barco = request.form.get('clase_barco')

    if rol == 'entrenador':
        google_forms_url = f"https://docs.google.com/forms/d/e/{GOOGLE_FORMS_ENTRENADORES_ID}/viewform?usp=pp_url"
        return redirect(google_forms_url)

    elif rol == 'competidor':
        total_price = BASE_PRECIOS['competidor']
        item_title = "Inscripción Competidor"
        
        if clase_barco and clase_barco in PRECIOS_BARCOS:
            total_price += PRECIOS_BARCOS[clase_barco]
            item_title += f" - {clase_barco}"
        else:
            return "Error: Por favor, selecciona tu clase de barco.", 400

        if mas_150km and clase_barco in PRECIOS_BENEFICIO:
            total_price = PRECIOS_BENEFICIO[clase_barco]
            item_title += " (Beneficio >150km)"

        total_price = max(1, round(total_price, 2))
        app.logger.info(f"Calculando precio para competidor: {item_title} -> Precio Final={total_price}")

        # En lugar de crear una preferencia y redirigir, ahora renderizamos una plantilla
        # con los datos necesarios para el Checkout Brick.
        return render_template(
            'checkout.html',
            item_title=item_title,
            amount=total_price,
            public_key=MERCADO_PAGO_PUBLIC_KEY,
            clase_barco=clase_barco
        )
    else:
        return "Error: Rol no válido seleccionado.", 400


@app.route('/process_payment', methods=['POST'])
def process_payment():
    """
    (NUEVA RUTA)
    Recibe los datos del pago desde el frontend (Checkout Brick),
    realiza el cobro y devuelve el resultado.
    """
    try:
        data = request.get_json()
        clase_barco = data.get("additional_data", {}).get("clase_barco")
        
        payment_data = {
            "transaction_amount": float(data["transaction_amount"]),
            "token": data["token"],
            "description": data["description"],
            "installments": int(data["installments"]),
            "payment_method_id": data["payment_method_id"],
            "payer": {
                "email": data["payer"]["email"],
                "first_name": data["payer"].get("first_name"), # Opcional
                "last_name": data["payer"].get("last_name")    # Opcional
            },
            "external_reference": f"METRO_{clase_barco or 'no_barco'}",
            "notification_url": f"{URL_BASE}/mercadopago-webhook" # ¡Importante mantener los webhooks!
        }

        app.logger.info(f"Procesando pago para: {payment_data['payer']['email']} por ${payment_data['transaction_amount']}")
        payment_response = sdk.payment().create(payment_data)
        payment = payment_response["response"]
        
        app.logger.info(f"Respuesta de MP: ID={payment['id']}, Estado={payment['status']}")

        # Devolvemos el estado y el ID del pago al frontend
        return jsonify({
            "status": payment["status"],
            "status_detail": payment["status_detail"],
            "id": payment["id"]
        })

    except Exception as e:
        app.logger.error(f"Error al procesar el pago: {e}")
        return jsonify({"error": str(e)}), 500


# --- RUTAS DE REDIRECCIÓN Y WEBHOOK (SE MANTIENEN IGUAL POR SEGURIDAD Y RESPALDO) ---
# Aunque el flujo principal ya no las usa para la redirección, los webhooks
# siguen siendo vitales para confirmar pagos que puedan quedar en estados intermedios.

@app.route('/payment_success') # Esta ruta ya no será alcanzada en el flujo normal
def payment_success():
    return render_template('payment_status.html', status="éxito", message="El pago fue registrado. ¡Gracias!")

@app.route('/payment_pending')
def payment_pending():
    return render_template('payment_status.html', status="pendiente", message="Tu pago está pendiente.")

@app.route('/payment_failure')
def payment_failure():
    return render_template('payment_status.html', status="fallido", message="Tu pago fue rechazado.")


@app.route('/mercadopago-webhook', methods=['POST'])
def mercadopago_webhook():
    """Endpoint para Webhooks, sin cambios, sigue siendo crucial."""
    data = request.json
    topic = data.get('topic')
    resource_id = data.get('id')
    app.logger.info(f"Webhook recibido. Topic: {topic}, Resource ID: {resource_id}")

    if topic == 'payment':
        try:
            payment_info = sdk.payment().get(resource_id)
            if payment_info and payment_info["status"] == 200:
                payment = payment_info["response"]
                # ... (tu lógica de base de datos aquí) ...
                app.logger.info(f"Webhook procesado para pago {payment['id']}, estado {payment['status']}.")
        except Exception as e:
            app.logger.error(f"Error procesando webhook de pago {resource_id}: {e}")
    
    return jsonify({"status": "ok"}), 200

# --- INICIAR EL SERVIDOR FLASK ---
if __name__ == '__main__':
    app.run(debug=False, port=5000)