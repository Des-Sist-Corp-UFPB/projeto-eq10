(function () {
    "use strict";

    function setupSidebarToggle() {
        var toggle = document.getElementById("sidebar-toggle");
        var sidebar = document.getElementById("app-sidebar");
        var backdrop = document.getElementById("sidebar-backdrop");
        if (!toggle || !sidebar || !backdrop) {
            return;
        }

        function closeSidebar() {
            sidebar.classList.remove("open");
            backdrop.classList.remove("open");
        }

        function openSidebar() {
            sidebar.classList.add("open");
            backdrop.classList.add("open");
        }

        toggle.addEventListener("click", function () {
            if (sidebar.classList.contains("open")) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });

        backdrop.addEventListener("click", closeSidebar);

        sidebar.querySelectorAll(".sidebar-link").forEach(function (link) {
            link.addEventListener("click", closeSidebar);
        });
    }

    function setupProfileMenu() {
        var trigger = document.getElementById("profile-trigger");
        var menu = document.getElementById("profile-menu");
        if (!trigger || !menu) {
            return;
        }

        function closeMenu() {
            menu.classList.remove("open");
        }

        trigger.addEventListener("click", function (event) {
            event.stopPropagation();
            menu.classList.toggle("open");
        });

        document.addEventListener("click", function (event) {
            if (!menu.contains(event.target) && event.target !== trigger) {
                closeMenu();
            }
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                closeMenu();
            }
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        setupSidebarToggle();
        setupProfileMenu();
    });
})();
