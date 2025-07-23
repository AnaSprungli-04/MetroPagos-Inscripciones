// static/js/redirect.js
document.addEventListener('DOMContentLoaded', function() {
    // La URL de Google Forms es pasada por Flask al template y luego por el script en success.html
    // Obtener la URL del atributo href del enlace de respaldo
    const googleFormsUrl = document.getElementById('redirectLink').href;

    if (googleFormsUrl) {
        // Redirigir después de un breve retraso para que el usuario vea el mensaje de éxito
        setTimeout(function() {
            window.location.href = googleFormsUrl;
        }, 3000); // Redirige después de 3 segundos (3000 milisegundos)
    } else {
        console.error("No se encontró la URL del formulario de Google para redireccionar.");
        // Podrías mostrar un mensaje de error o un enlace manual
    }
});