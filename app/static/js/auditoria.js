(function () {
    "use strict";

    document.addEventListener("DOMContentLoaded", function () {
        var backdrop = document.getElementById("audit-detail-backdrop");
        var modal = document.getElementById("audit-detail-modal");
        var closeBtn = document.getElementById("audit-detail-close");
        if (!backdrop || !modal) {
            return;
        }

        function closeModal() {
            modal.classList.remove("open");
            backdrop.classList.remove("open");
        }

        function openModalFromRow(row) {
            document.getElementById("audit-detail-evento").textContent = row.dataset.evento || "-";
            document.getElementById("audit-detail-data-hora").textContent = row.dataset.dataHora || "-";
            document.getElementById("audit-detail-email").textContent = row.dataset.email || "-";
            document.getElementById("audit-detail-prompt").textContent = row.dataset.prompt || "-";
            document.getElementById("audit-detail-detalhe").textContent = row.dataset.detalhe || "-";
            document.getElementById("audit-detail-metadados").textContent = row.dataset.metadados || "-";

            var statusEl = document.getElementById("audit-detail-status");
            statusEl.textContent = row.dataset.statusLabel || "-";
            statusEl.className = "status-badge status-" + (row.dataset.statusKey || "info");

            modal.classList.add("open");
            backdrop.classList.add("open");
        }

        document.querySelectorAll(".audit-row").forEach(function (row) {
            row.addEventListener("click", function () {
                openModalFromRow(row);
            });
        });

        backdrop.addEventListener("click", closeModal);
        if (closeBtn) {
            closeBtn.addEventListener("click", closeModal);
        }
        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                closeModal();
            }
        });
    });
})();
