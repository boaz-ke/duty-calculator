(function () {
    "use strict";

    const cfg = window.CALC_APP || {};
    const searchInput = document.getElementById("vehicle-search");
    const resultsBox = document.getElementById("search-results");
    const selectionNote = document.getElementById("selection-note");
    const vehicleType = document.getElementById("vehicle-type");
    const fuel = document.getElementById("fuel");
    const engineCc = document.getElementById("engine-cc");
    const crsp = document.getElementById("crsp");
    const calcForm = document.getElementById("calc-form");
    const resultBox = document.getElementById("result");
    const emptyBox = document.getElementById("result-empty");
    const errorBox = document.getElementById("result-error");
    const amountBody = document.getElementById("amount-body");

    let searchTimer = null;
    let selectedRow = null;

    const BODY_TO_TYPE = {
        suv: "passenger", sedan: "passenger", wagon: "passenger",
        hatchback: "passenger", coupe: "passenger", convertible: "passenger",
        minivan: "van_minibus", van: "van_minibus",
        pickup: "pickup", truck: "bus", bus: "bus",
        ambulance: "ambulance", machinery: "machinery", prime_mover: "prime_mover",
    };

    function setVisible(field, visible) {
        if (!field) return;
        const wrapper = field.closest(".field, .field-row > .field, .field-row");
        if (wrapper) {
            wrapper.style.display = visible ? "" : "none";
        }
    }

    function refreshTypeFields() {
        const type = vehicleType.value;
        const needsSpecs = ["passenger", "pickup", "van_minibus", "bus"].includes(type);
        setVisible(fuel, needsSpecs);
        setVisible(engineCc, needsSpecs);
    }

    vehicleType.addEventListener("change", refreshTypeFields);
    refreshTypeFields();

    function fmtKES(value) {
        return "KES " + Number(value || 0).toLocaleString("en-KE", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    function showError(message) {
        errorBox.textContent = message;
        errorBox.hidden = false;
        resultBox.hidden = true;
        emptyBox.hidden = true;
    }

    function clearError() {
        errorBox.hidden = true;
    }

    async function search() {
        const q = (searchInput.value || "").trim();
        resultsBox.innerHTML = "";
        if (q.length < 2) {
            resultsBox.hidden = true;
            return;
        }
        const response = await fetch(cfg.searchUrl + "?q=" + encodeURIComponent(q));
        if (!response.ok) return;
        const data = await response.json();
        if (!data.results || !data.results.length) {
            resultsBox.hidden = true;
            return;
        }
        for (const row of data.results) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "search-item";
            button.innerHTML =
                '<span class="price">' + fmtKES(row.crsp) + "</span>" +
                "<strong>" + escapeHtml(row.display) + "</strong>" +
                "<small>" + escapeHtml(row.spec || "") + "</small>";
            button.addEventListener("click", () => selectRow(row));
            resultsBox.appendChild(button);
        }
        resultsBox.hidden = false;
    }

    function escapeHtml(value) {
        return String(value).replace(/[&<>"']/g, (ch) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
        }[ch]));
    }

    document.querySelectorAll(".example-chip").forEach((chip) => {
        chip.addEventListener("click", async () => {
            const q = chip.dataset.query || "";
            searchInput.value = q;
            clearTimeout(searchTimer);
            const response = await fetch(cfg.searchUrl + "?q=" + encodeURIComponent(q));
            if (!response.ok) return;
            const data = await response.json();
            if (data.results && data.results.length) {
                selectRow(data.results[0]);
                searchInput.focus();
            }
        });
    });

    function selectRow(row) {
        selectedRow = row;
        searchInput.value = row.display;
        resultsBox.hidden = true;
        selectionNote.textContent =
            "Catalogue match selected — details below were auto-filled. You can still adjust them.";
        selectionNote.classList.add("is-match");
        const type =
            row.category === "motorcycle" ? "motorcycle" :
            row.category === "machinery" ? "machinery" :
            BODY_TO_TYPE[row.body_class] || "passenger";
        vehicleType.value = type;
        fuel.value = ["petrol", "diesel", "electric", "hybrid"].includes(row.fuel_class)
            ? row.fuel_class : "";
        engineCc.value = row.engine_cc != null ? Math.round(row.engine_cc) : "";
        crsp.value = row.crsp != null ? row.crsp : "";
        refreshTypeFields();
        clearError();
    }

    searchInput.addEventListener("input", () => {
        selectedRow = null;
        selectionNote.textContent = "No catalogue match? Enter the details manually below.";
        selectionNote.classList.remove("is-match");
        clearTimeout(searchTimer);
        searchTimer = setTimeout(search, 280);
    });
    document.addEventListener("click", (event) => {
        if (!searchInput.contains(event.target) && !resultsBox.contains(event.target)) {
            resultsBox.hidden = true;
        }
    });

    crsp.addEventListener("input", () => {
        selectedRow = null;
        selectionNote.textContent = "No catalogue match? Enter the details manually below.";
        selectionNote.classList.remove("is-match");
    });

    const rows = [
        ["Customs value", "customs_value"],
        ["Import duty", "import_duty"],
        ["Excise value", "excise_value"],
        ["Excise duty", "excise_duty"],
        ["VAT value", "vat_base"],
        ["VAT (16%)", "vat"],
        ["RDL (2%)", "rdl"],
        ["IDF (2.5%)", "idf"],
    ];

    calcForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        clearError();
        const body = {
            route: new FormData(calcForm).get("route"),
            vehicle_type: vehicleType.value,
            fuel: fuel.value,
            engine_cc: engineCc.value,
            yom: document.getElementById("yom").value,
            extra_depreciation: document.getElementById("extra-dep").value || 0,
            crsp: crsp.value,
        };
        try {
            const response = await fetch(cfg.calculateUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            const data = await response.json();
            if (!response.ok) {
                showError(data.error || "Calculation failed.");
                return;
            }

            document.getElementById("result-vehicle").textContent =
                selectedRow ? selectedRow.display : vehicleType.options[vehicleType.selectedIndex].text;
            document.getElementById("result-route").textContent =
                data.route_label + " · " + data.age + " year(s) old · " +
                (data.depreciation_rate * 100).toFixed(0) + "% depreciation";
            amountBody.innerHTML = "";
            for (const [label, key] of rows) {
                if (key === "rdl" || key === "idf") {
                    if (data.result[key] === 0) continue;
                }
                const tr = document.createElement("tr");
                const td1 = document.createElement("td");
                td1.textContent = label;
                const td2 = document.createElement("td");
                td2.textContent = fmtKES(data.result[key]);
                tr.append(td1, td2);
                amountBody.appendChild(tr);
            }
            document.getElementById("grand-total").textContent = fmtKES(data.result.grand_total);
            document.getElementById("per-1000").textContent =
                "Tax per KES 1,000 of CRSP: " + fmtKES(data.result.per_1000);
            emptyBox.hidden = true;
            resultBox.hidden = false;
            resultBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
        } catch (err) {
            showError("Could not reach the calculator. Try again.");
        }
    });
})();
