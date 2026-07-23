(function () {
  "use strict";

  var cert = document.getElementById("winner-certificate");
  var statusEl = document.getElementById("cert-status");
  var printBtn = document.getElementById("cert-print-btn");
  var downloadBtn = document.getElementById("cert-download-btn");
  var shareBtn = document.getElementById("cert-share-btn");
  var copyBtn = document.getElementById("cert-copy-btn");

  function setStatus(msg) {
    if (!statusEl) return;
    statusEl.hidden = !msg;
    statusEl.textContent = msg || "";
  }

  function filenameBase() {
    var raw = (cert && cert.getAttribute("data-filename")) || "certificado";
    return String(raw)
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-zA-Z0-9-_]+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "")
      .toLowerCase() || "certificado";
  }

  function renderCanvas() {
    if (!cert) return Promise.reject(new Error("Certificado no encontrado"));
    if (typeof html2canvas !== "function") {
      return Promise.reject(new Error("html2canvas no está disponible"));
    }
    return html2canvas(cert, {
      scale: 2,
      useCORS: true,
      allowTaint: false,
      backgroundColor: "#070d1a",
      logging: false,
      // Prefer layout box for a stable landscape capture.
      windowWidth: Math.max(cert.scrollWidth, 1100),
    });
  }

  function canvasToBlob(canvas) {
    return new Promise(function (resolve, reject) {
      canvas.toBlob(function (blob) {
        if (blob) resolve(blob);
        else reject(new Error("No se pudo generar la imagen"));
      }, "image/png");
    });
  }

  function downloadBlob(blob, name) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1500);
  }

  async function buildImageBlob() {
    var canvas = await renderCanvas();
    return canvasToBlob(canvas);
  }

  async function downloadImage() {
    setStatus("Generando imagen…");
    var blob = await buildImageBlob();
    downloadBlob(blob, filenameBase() + ".png");
    setStatus("Imagen descargada.");
    return true;
  }

  async function copyUrl() {
    var url =
      (copyBtn && copyBtn.getAttribute("data-url")) ||
      (cert && cert.getAttribute("data-share-url")) ||
      window.location.href;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(url);
      } else {
        var input = document.createElement("input");
        input.value = url;
        document.body.appendChild(input);
        input.select();
        document.execCommand("copy");
        input.remove();
      }
      setStatus("Enlace público copiado.");
      return true;
    } catch (err) {
      setStatus("No se pudo copiar el enlace: " + url);
      return false;
    }
  }

  async function shareCertificate() {
    var title = (cert && cert.getAttribute("data-share-title")) || document.title;
    var text = (cert && cert.getAttribute("data-share-text")) || "";
    var url = (cert && cert.getAttribute("data-share-url")) || window.location.href;

    if (navigator.share) {
      try {
        setStatus("Preparando para compartir…");
        var blob = await buildImageBlob();
        var file = new File([blob], filenameBase() + ".png", { type: "image/png" });
        var payload = { title: title, text: text, url: url };
        if (navigator.canShare && navigator.canShare({ files: [file] })) {
          payload.files = [file];
        }
        await navigator.share(payload);
        setStatus("Compartido.");
        return;
      } catch (err) {
        if (err && err.name === "AbortError") {
          setStatus("");
          return;
        }
        // Fall through to download / copy fallbacks.
      }
    }

    try {
      await downloadImage();
      setStatus("Compartir no disponible; se descargó la imagen. También puedes copiar el enlace.");
    } catch (downloadErr) {
      setStatus((downloadErr && downloadErr.message) || "No se pudo descargar la imagen.");
      await copyUrl();
    }
  }

  if (printBtn) {
    printBtn.addEventListener("click", function () {
      window.print();
    });
  }
  if (downloadBtn) {
    downloadBtn.addEventListener("click", function () {
      downloadImage().catch(function (err) {
        setStatus((err && err.message) || "No se pudo descargar la imagen.");
      });
    });
  }
  if (shareBtn) {
    shareBtn.addEventListener("click", function () {
      shareCertificate();
    });
  }
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      copyUrl();
    });
  }
})();
