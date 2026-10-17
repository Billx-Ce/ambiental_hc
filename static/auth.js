"use strict";
document.querySelectorAll("[data-password-target]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.passwordTarget);
    const visible = input.type === "password";
    input.type = visible ? "text" : "password";
    button.textContent = visible ? "Ocultar" : "Mostrar";
    button.setAttribute("aria-pressed", String(visible));
  });
});
document.querySelector(".auth-form").addEventListener("submit", (event) => {
  if (!event.currentTarget.checkValidity()) return;
  event.currentTarget.querySelector("button[type=submit]").disabled = true;
  document.getElementById("auth-progress").textContent = "Procesando…";
});
window.addEventListener("pageshow", () => {
  document.querySelector("button[type=submit]").disabled = false;
  document.getElementById("auth-progress").textContent = "";
});
