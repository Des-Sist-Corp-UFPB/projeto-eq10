(function () {
    "use strict";

    function appendRow(stack, role, html) {
        var row = document.createElement("div");
        row.className = "chat-row " + role;
        row.innerHTML =
            '<div class="chat-bubble ' + role + '">' +
            '<span class="chat-label">' + (role === "user" ? "Você" : "Assistente") + "</span>" +
            '<div class="chat-content">' + html + "</div>" +
            "</div>";
        stack.appendChild(row);
        return row;
    }

    function appendProcessingRow(stack) {
        return appendRow(
            stack,
            "assistant",
            '<div class="processing-content"><span>Processando pergunta...</span>' +
            '<span class="processing-dots" aria-hidden="true"><span></span><span></span><span></span></span></div>'
        );
    }

    function ensureStack() {
        var stack = document.getElementById("chat-stack");
        if (stack) {
            return stack;
        }
        stack = document.createElement("section");
        stack.className = "chat-stack";
        stack.id = "chat-stack";
        var form = document.getElementById("chat-form");
        form.parentNode.insertBefore(stack, form);
        return stack;
    }

    function submitPrompt(promptText) {
        var form = document.getElementById("chat-form");
        var input = document.getElementById("chat-prompt");
        var submitBtn = document.getElementById("chat-submit");
        var stack = ensureStack();

        input.value = "";
        input.disabled = true;
        submitBtn.disabled = true;

        appendRow(stack, "user", '<p>' + escapeHtml(promptText) + "</p>");
        var processingRow = appendProcessingRow(stack);
        processingRow.scrollIntoView({ behavior: "smooth", block: "end" });

        var body = new URLSearchParams();
        body.set("prompt", promptText);

        fetch("/chat/ask", {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: body.toString(),
        })
            .then(function (response) {
                if (response.status === 401) {
                    window.location.href = "/auth/login?next=/chat";
                    return null;
                }
                return response.json().then(function (data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function (result) {
                processingRow.remove();
                if (!result) {
                    return;
                }
                if (!result.ok) {
                    appendRow(stack, "assistant", "<p>Não foi possível processar sua pergunta agora. Tente novamente.</p>");
                    return;
                }
                appendRow(stack, "assistant", result.data.assistant_html);
                var lastRow = stack.lastElementChild;
                if (lastRow) {
                    lastRow.scrollIntoView({ behavior: "smooth", block: "end" });
                }
            })
            .catch(function () {
                processingRow.remove();
                appendRow(stack, "assistant", "<p>Não foi possível processar sua pergunta agora. Tente novamente.</p>");
            })
            .finally(function () {
                input.disabled = false;
                submitBtn.disabled = false;
                input.focus();
            });
    }

    function escapeHtml(value) {
        var div = document.createElement("div");
        div.textContent = value;
        return div.innerHTML;
    }

    document.addEventListener("DOMContentLoaded", function () {
        var form = document.getElementById("chat-form");
        if (!form) {
            return;
        }

        form.addEventListener("submit", function (event) {
            event.preventDefault();
            var input = document.getElementById("chat-prompt");
            var promptText = input.value.trim();
            if (!promptText) {
                return;
            }
            submitPrompt(promptText);
        });

        document.querySelectorAll(".suggestion-chip").forEach(function (chip) {
            chip.addEventListener("click", function () {
                submitPrompt(chip.textContent.trim());
            });
        });
    });
})();
