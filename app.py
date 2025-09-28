from flask import Flask, render_template, request, redirect, url_for, jsonify
import mercadopago
from flask import session, flash
import os
import logging
import urllib.parse
import json
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import re 

load_dotenv()
app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

app.logger.setLevel(logging.INFO)

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), 'settings.json')
ALLOWED_LOGO_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

# 💥 CAMBIO CLAVE: URL_BASE se lee del entorno con un fallback (valor por defecto)
URL_BASE = os.environ.get("URL_BASE", "https://metropolitanopagos-inscripciones.onrender.com") 

# --- Función Auxiliar para Extracción de ID ---
def extract_form_id(url_or_id):
    """
    Extrae el ID único del formulario (la cadena entre /d/e/ y /viewform o /edit).
    Si se proporciona un ID limpio, lo devuelve.
    """
    # 1. Patrón para buscar IDs largos de Google Forms (después de /d/e/)
    match = re.search(r'/d/e/([a-zA-Z0-9_-]+)(?:/viewform|/edit|/formResponse)?', url_or_id)
    if match:
        return match.group(1)
    
    # 2. Patrón para IDs más cortos (raros, pero para cubrir)
    match = re.search(r'/d/([a-zA-Z0-9_-]+)(?:/viewform|/edit|/formResponse)?', url_or_id)
    if match:
        return match.group(1)

    # 3. Si no es una URL, asumimos que ya es el ID limpio
    return url_or_id.strip()

# ---------------------------------------------

def load_settings():
    try:
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            settings = json.load(f)
            # Asegurar que las claves existan para evitar errores
            if "google_forms" not in settings:
                settings["google_forms"] = {
                    "competitors_id": "1FAIpQLSeA0tbwyKZ-u8zra-W6hlJL8TCTQOayqCpKwya3sON0ubS0nA",
                    "trainers_id": "1FAIpQLSeZGar2xA3OR6SwNbKatSj1CLWQjRTmWyM0t-LOabpRWZYZ4g",
                    "entry_id_num_operacion": "entry.1161481877",
                    "entry_id_clase_barco": "entry.1553765108"
                }
            # 💥 ELIMINADO: Ya no se maneja "url_base" en settings
            if "url_base" in settings:
                del settings["url_base"] # Limpieza si existía en un JSON viejo

            if "allow_cash_payments" not in settings:
                settings["allow_cash_payments"] = True
            if "discount_enabled" not in settings:
                settings["discount_enabled"] = False
            if "discount_description" not in settings:
                settings["discount_description"] = ""
            if "discount_percentage" not in settings:
                settings["discount_percentage"] = 0
            
            # Asegurar que cada clase tenga un precio de descuento (aunque ahora se calcula)
            for cls in settings.get("classes", []):
                if "discount_price" not in cls:
                    cls["discount_price"] = None 

            return settings
    except Exception:
        return {
            "logo": "static/images/Metropolitano.png",
            "title_main": "Inscripciones",
            "title_strong": "Metropolitano",
            "base_price": 0,
            "site_closed": False,
            "classes": [],
            "google_forms": {
                "competitors_id": "1FAIpQLSeA0tbwyKZ-u8zra-W6hlJL8TCTQOayqCpKwya3sON0ubS0nA",
                "trainers_id": "1FAIpQLSeZGar2xA3OR6SwNbKatSj1CLWQjRTmWyM0t-LOabpRWZYZ4g",
                "entry_id_num_operacion": "entry.1161481877",
                "entry_id_clase_barco": "entry.1553765108"
            },
            # 💥 ELIMINADO: Ya no se maneja "url_base" en settings
            "allow_cash_payments": True,
            "discount_enabled": False,
            "discount_percentage": 0,
            "discount_description": ""
        }

def save_settings(data):
    with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def allowed_logo(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_LOGO_EXTENSIONS
    
MERCADO_PAGO_ACCESS_TOKEN = os.environ.get("MERCADO_PAGO_ACCESS_TOKEN")
sdk = mercadopago.SDK(MERCADO_PAGO_ACCESS_TOKEN)

app.logger.info(f"DEBBUGING: {MERCADO_PAGO_ACCESS_TOKEN[:10]}")


@app.route('/')
def index():
    settings = load_settings()
    if settings.get("site_closed"):
        return render_template('cerrada.html', page_title="Inscripción cerrada")
    
    return redirect(url_for('inscripciones'))

@app.route('/process_inscription', methods=['POST'])
def process_inscription():
    rol = request.form.get('rol')
    settings = load_settings()
    # 💥 MODIFICADO: Ahora usa la constante global URL_BASE
    
    if settings.get("site_closed"):
        return render_template('cerrada.html', page_title="Inscripción cerrada"), 403
    
    clase_barco = request.form.get('clase_barco')
    
    apply_discount = request.form.get('apply_discount') == 'on'

    if rol == 'entrenador':
        google_forms_id = settings["google_forms"]["trainers_id"]
        google_forms_url = (
            f"https://docs.google.com/forms/d/e/{google_forms_id}/viewform?"
            f"usp=pp_url"
        )
        app.logger.info(f"Entrenador detectado. Redirigiendo a su formulario específico: {google_forms_url}")
        return redirect(google_forms_url)

    elif rol == 'competidor':
        clases_habilitadas = [c["name"] for c in settings.get("classes", []) if not c.get("closed", False)]
        if clase_barco not in clases_habilitadas:
            app.logger.warning(f"Intento de inscripcion a clase cerrada: {clase_barco}")
            return "La inscripcion para esta clase esta cerrada. Por favor, selecciona una clase habilitada.", 403
        
        total_price = 0
        item_title = "Inscripcion Competidor"
        
        if clase_barco:
            class_info = None
            for c in settings.get("classes", []):
                if c.get("name") == clase_barco:
                    class_info = c
                    break
            
            if class_info is None:
                app.logger.error("Competidor sin clase de barco o clase de barco inválida.")
                return "Error: Por favor, selecciona tu clase de barco.", 400
            
            is_discounted = settings.get("discount_enabled") and apply_discount and class_info.get("price") is not None
            
            if is_discounted:
                original_price = int(class_info["price"])
                discount_percentage = int(settings.get("discount_percentage", 0))
                
                total_price = original_price * (1 - discount_percentage / 100)
                total_price = max(1, round(total_price, 2)) 
                
                item_title += f" - {clase_barco} ({settings.get('discount_description', 'Descuento aplicado')})"
            else:
                total_price = int(class_info["price"])
                item_title += f" - {clase_barco}"
                
        else:
            app.logger.error("Competidor sin clase de barco o clase de barco inválida.")
            return "Error: Por favor, selecciona tu clase de barco.", 400

        total_price = max(1, round(total_price, 2))

        app.logger.info(f"Calculando precio para competidor: Rol={rol}, Barco={clase_barco}, Desc. Aplicado={is_discounted} -> Precio Final={total_price}")

        encoded_clase_barco = urllib.parse.quote_plus(clase_barco)
        
        excluded_payment_types = []
        if not settings["allow_cash_payments"]:
            excluded_payment_types.append({"id": "ticket"})

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
                # 💥 USO de la constante global URL_BASE
                "success": f"{URL_BASE}/payment_success?clase_barco={encoded_clase_barco}",
                "pending": f"{URL_BASE}/payment_pending?clase_barco={encoded_clase_barco}",
                "failure": f"{URL_BASE}/payment_failure?clase_barco={encoded_clase_barco}"
            },
            "auto_return": "approved",
            "external_reference": f"METRO_{clase_barco or 'no_barco'}",
            "payment_methods": {
                "excluded_payment_types": excluded_payment_types
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
    payment_id = request.args.get('payment_id')
    status = request.args.get('status')
    collection_id = request.args.get('collection_id')
    clase_barco = request.args.get('clase_barco')
    settings = load_settings()
    google_forms_id = settings["google_forms"]["competitors_id"]
    entry_id_num_operacion = settings["google_forms"]["entry_id_num_operacion"]
    entry_id_clase_barco = settings["google_forms"]["entry_id_clase_barco"]

    app.logger.info(f"Redirección de éxito de MP recibida. Payment ID: {payment_id}, Status: {status}, Collection ID: {collection_id}, Clase Barco: {clase_barco}")

    google_forms_url_competidor = (
        f"https://docs.google.com/forms/d/e/{google_forms_id}/viewform?"
        f"usp=pp_url&{entry_id_num_operacion}={payment_id}"
    )

    if clase_barco:
        encoded_clase_barco_for_form = urllib.parse.quote_plus(clase_barco)
        google_forms_url_competidor += f"&{entry_id_clase_barco}={encoded_clase_barco_for_form}"

    return render_template('success.html',
                           message="¡Tu pago fue procesado con Exito! Por favor, verifica tu correo o continua con los pasos adicionales.",
                           payment_id=payment_id,
                           google_forms_url=google_forms_url_competidor)

@app.route('/payment_pending')
def payment_pending():
    payment_id = request.args.get('payment_id')
    status = request.args.get('status')
    clase_barco = request.args.get('clase_barco')
    app.logger.info(f"Redirección de pendiente de MP recibida. Payment ID: {payment_id}, Status: {status}, Clase Barco: {clase_barco}")
    return render_template('payment_status.html', status="pendiente", message="Tu pago está pendiente de aprobación. Por favor, revisa el estado de tu pago en Mercado Pago.")

@app.route('/payment_failure')
def payment_failure():
    payment_id = request.args.get('payment_id')
    status = request.args.get('status')
    clase_barco = request.args.get('clase_barco')
    app.logger.info(f"Redirección de fallo de MP recibida. Payment ID: {payment_id}, Status: {status}, Clase Barco: {clase_barco}")
    return render_template('payment_status.html', status="fallido", message="Tu pago no pudo ser procesado. Por favor, verifica tus datos o intenta con otro método de pago.")

@app.route('/mercadopago-webhook', methods=['POST'])
def mercadopago_webhook():
    data = request.json
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
                if payment_status == 'approved':
                    app.logger.info(f"Pago {payment_id} APROBADO. Actualizando estado de inscripcion para {external_reference}.")
                elif payment_status == 'pending':
                    app.logger.info(f"Pago {payment_id} PENDIENTE. Actualizando estado de inscripcion para {external_reference}.")
                elif payment_status == 'rejected':
                    app.logger.info(f"Pago {payment_id} RECHAZADO. Actualizando estado de inscripcion para {external_reference}.")
            else:
                app.logger.error(f"Error al obtener detalles del pago {resource_id} desde el webhook: {payment_info}")
        except Exception as e:
            app.logger.error(f"Excepcion al procesar webhook de pago {resource_id}: {e}")
    return jsonify({"status": "ok"}), 200

@app.before_request
def site_closed_gate():
    try:
        if request.path.startswith('/admin') or request.path.startswith('/static') or request.path == '/':
            return
        settings = load_settings()
        if settings.get('site_closed'):
            return render_template('cerrada.html', page_title="Inscripción cerrada")
    except Exception:
        pass

@app.route('/inscripciones')
def inscripciones():
    settings = load_settings()
    if settings.get("site_closed"):
        return render_template('cerrada.html', page_title="Inscripción cerrada")
    
    logo_path = settings.get("logo", "static/images/Metropolitano.png")
    title_main = settings.get("title_main", "Inscripciones")
    title_strong = settings.get("title_strong", "Metropolitano")
    
    classes = settings.get("classes", [])
    
    sorted_classes = sorted(classes, key=lambda cls: cls.get("closed", False))
    
    enabled_classes = [c["name"] for c in sorted_classes if not c.get("closed", False)]
    
    discount_enabled = settings.get("discount_enabled", False)
    discount_description = settings.get("discount_description", "")
    
    return render_template(
        'index.html',
        page_title=f"{title_main} {title_strong}",
        logo_path=logo_path,
        title_main=title_main,
        title_strong=title_strong,
        classes=sorted_classes, 
        enabled_classes=enabled_classes,
        discount_enabled=discount_enabled,
        discount_description=discount_description
    )


# --- ADMIN ---
@app.route('/admin', methods=['GET'])
def admin_home():
    if not session.get('is_admin'):
        return render_template('admin_login.html')
    settings = load_settings()
    # 💥 MODIFICADO: URL_BASE ya no está en settings, se pasa como variable separada (si es necesario)
    return render_template('admin.html', settings=settings, current_url_base=URL_BASE)

@app.route('/admin/login', methods=['POST'])
def admin_login():
    password = request.form.get('password', '')
    expected = os.environ.get('ADMIN_PASSWORD')
    if expected and password == expected:
        session['is_admin'] = True
        return redirect(url_for('admin_home'))
    flash('Contraseña incorrecta', 'danger')
    return redirect(url_for('admin_home'))

@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    session.clear()
    return redirect(url_for('admin_home'))

@app.route('/admin/save', methods=['POST'])
def admin_save():
    if not session.get('is_admin'):
        return redirect(url_for('admin_home'))
    
    settings = load_settings()
    delete_idx = request.form.get('delete')
    if delete_idx is not None:
        try:
            di = int(delete_idx)
            classes = settings.get('classes', [])
            if 0 <= di < len(classes):
                classes.pop(di)
                settings['classes'] = classes
                save_settings(settings)
                flash('Clase eliminada', 'success')
                return redirect(url_for('admin_home'))
        except Exception:
            flash('No se pudo eliminar la clase', 'danger')
            return redirect(url_for('admin_home'))
    
    settings['title_main'] = request.form.get('title_main', settings.get('title_main', 'Inscripciones')).strip()
    settings['title_strong'] = request.form.get('title_strong', settings.get('title_strong', 'Metropolitano')).strip()

    # Extracción de IDs de Google Forms
    competitors_url_or_id = request.form.get('google_forms_competitors_id', settings["google_forms"]["competitors_id"]).strip()
    settings["google_forms"]["competitors_id"] = extract_form_id(competitors_url_or_id)
    
    trainers_url_or_id = request.form.get('google_forms_trainers_id', settings["google_forms"]["trainers_id"]).strip()
    settings["google_forms"]["trainers_id"] = extract_form_id(trainers_url_or_id)
    
    # IDs de Entrada del formulario
    settings["google_forms"]["entry_id_num_operacion"] = request.form.get('entry_id_num_operacion', settings["google_forms"]["entry_id_num_operacion"]).strip()
    settings["google_forms"]["entry_id_clase_barco"] = request.form.get('entry_id_clase_barco', settings["google_forms"]["entry_id_clase_barco"]).strip()
    
    # 💥 ELIMINADO: Ya no se guarda "url_base" aquí. Se maneja vía environment.

    settings["allow_cash_payments"] = request.form.get('allow_cash_payments') == 'on'
    
    settings["discount_enabled"] = request.form.get('discount_enabled') == 'on'
    settings["discount_description"] = request.form.get('discount_description', '').strip()
    
    try:
        settings["discount_percentage"] = int(request.form.get('discount_percentage', 0))
    except ValueError:
        flash('El porcentaje de descuento debe ser un número entero válido.', 'danger')
        return redirect(url_for('admin_home'))

    updated_classes = []
    for idx, cls in enumerate(settings.get('classes', [])):
        open_checked = request.form.get(f'open-{idx}') == 'on'
        closed = not open_checked
        name = request.form.get(f'name-{idx}', cls.get('name')).strip()
        price_val = request.form.get(f'price-{idx}')
        
        try:
            price = int(price_val) if price_val else cls.get('price')
            discount_price = None 
            
        except Exception:
            price = cls.get('price')
            discount_price = None
            
        if name:
            updated_classes.append({"name": name, "closed": closed, "price": price, "discount_price": discount_price})
    
    new_class = request.form.get('new_class', '').strip()
    if new_class:
        names_lower = {c['name'].lower() for c in updated_classes}
        if new_class.lower() not in names_lower:
            new_closed = False 
            new_price_val = request.form.get('new_class_price')
            try:
                new_price = int(new_price_val) if new_price_val else None
                new_discount_price = None 
            except Exception:
                new_price = None
                new_discount_price = None
            updated_classes.append({"name": new_class, "closed": new_closed, "price": new_price, "discount_price": new_discount_price})
    
    settings['classes'] = updated_classes
    
    if 'logo' in request.files:
        file = request.files['logo']
        if file and file.filename:
            filename = secure_filename(file.filename)
            ext_ok = "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_LOGO_EXTENSIONS
            if ext_ok:
                dest_dir = os.path.join(os.path.dirname(__file__), 'static', 'images')
                os.makedirs(dest_dir, exist_ok=True)
                save_name = f"logo_{filename}"
                file.save(os.path.join(dest_dir, save_name))
                settings['logo'] = f"static/images/{save_name}"
            else:
                flash('Formato de imagen no permitido', 'warning')

    save_settings(settings)
    flash('Cambios guardados', 'success')
    return redirect(url_for('admin_home'))

@app.route('/admin/site_state', methods=['POST'])
def admin_site_state():
    if not session.get('is_admin'):
        return redirect(url_for('admin_home'))
    action = request.form.get('action')
    settings = load_settings()
    if action == 'close':
        settings['site_closed'] = True
        flash('Inscripciones cerradas', 'warning')
    elif action == 'open':
        settings['site_closed'] = False
        flash('Inscripciones abiertas', 'success')
    save_settings(settings)
    return redirect(url_for('admin_home'))

if __name__ == '__main__':
    app.run(debug=False, port=5000)