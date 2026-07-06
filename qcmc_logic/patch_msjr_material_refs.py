"""
Add Material References section (HTML field) to MSJR and create its client script.
Run with: bench --site erp.qcstyro.local execute qcmc_logic.patch_msjr_material_refs.run
"""
import json, os
import frappe

SCRIPT_NAME = "Machine Shop Job Request - Material References"

# ---------------------------------------------------------------------------
# JavaScript for the client script
# ---------------------------------------------------------------------------

SCRIPT_JS = r"""
frappe.ui.form.on("Machine Shop Job Request", {
    refresh(frm) {
        if (frm.is_new()) return;
        _mref_render(frm);
    },
});

// ── fetch + render ────────────────────────────────────────────────────────────
function _mref_render(frm) {
    const field = frm.fields_dict["material_references_html"];
    if (!field) return;
    const $wrap = field.$wrapper;
    $wrap.html('<div class="text-muted p-2" style="font-size:12px">Loading material references…</div>');

    frappe.call({
        method: "qcmc_logic.utils.get_msjr_material_references",
        args: { msjr_no: frm.doc.name },
        callback(r) {
            const rows = r.message || [];
            if (!rows.length) {
                $wrap.html('<div class="text-muted p-2" style="font-size:12px">No material transactions linked to this MSJR.</div>');
                return;
            }
            $wrap.html(_mref_build(rows));
            _mref_init($wrap, rows.length);
        },
    });
}

// ── HTML builder ──────────────────────────────────────────────────────────────
function _mref_build(rows) {
    // assign group index for alternating row shading
    let grp = 0, prev = null;
    const tagged = rows.map(r => {
        if (r.doc_no !== prev) { grp++; prev = r.doc_no; }
        return Object.assign({}, r, { _grp: grp });
    });

    const STATUS_CLS = {
        Draft: "gray", Submitted: "blue", Cancelled: "red",
        Pending: "orange", Approved: "green", Ordered: "blue",
        Received: "green", Stopped: "red", Issued: "green",
        "Partially Ordered": "orange", "Partially Received": "orange",
    };

    const esc = s => frappe.utils.escape_html(String(s ?? ""));
    const fnum = v => (v == null ? "" : frappe.format(v, { fieldtype: "Float" }));
    const fdate = v => (v ? frappe.datetime.str_to_user(v) : "");

    const th = (col, lbl, cls = "") =>
        `<th data-col="${col}" class="${cls}" style="cursor:pointer;white-space:nowrap;user-select:none">${lbl}</th>`;

    const rows_html = tagged.map(r => {
        const bg = r._grp % 2 === 0 ? "#ffffff" : "#f8f9fa";
        const type_lbl = r.doctype === "Material Request" ? "MR" : "SE";
        const type_style = r.doctype === "Material Request"
            ? "background:#dbeafe;color:#1e40af;border:1px solid #bfdbfe"
            : "background:#fef3c7;color:#92400e;border:1px solid #fde68a";
        const status_cls = STATUS_CLS[r.status] || "gray";
        return `<tr style="background:${bg}" data-row>
            <td><span class="indicator-pill no-margin ${type_style}" style="font-size:10px;padding:1px 6px;border-radius:4px">${type_lbl}</span></td>
            <td style="font-family:monospace;font-size:11px">${esc(r.doc_no)}</td>
            <td>${fdate(r.date)}</td>
            <td><span class="indicator-pill ${status_cls} filterable">${esc(r.status)}</span></td>
            <td>${esc(r.created_by)}</td>
            <td style="font-family:monospace;font-size:11px">${esc(r.item_code)}</td>
            <td style="white-space:normal;min-width:160px">${esc(r.item_name)}</td>
            <td class="text-right">${fnum(r.requested_qty)}</td>
            <td class="text-right">${fnum(r.issued_qty)}</td>
            <td>${esc(r.uom)}</td>
        </tr>`;
    }).join("");

    return `
<div style="margin-top:4px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
    <input class="mref-search form-control form-control-sm"
           placeholder="Filter rows…" style="max-width:220px">
    <span class="mref-count text-muted" style="font-size:12px"></span>
    <button class="btn btn-xs btn-default mref-refresh" style="margin-left:auto">
        <i class="fa fa-refresh"></i> Refresh
    </button>
  </div>
  <div style="overflow-x:auto;border:1px solid #d1d5db;border-radius:4px">
    <table class="table table-bordered table-sm mref-table"
           style="font-size:12px;margin:0;white-space:nowrap">
      <thead class="thead-light">
        <tr>
          ${th("doctype",       "Type")}
          ${th("doc_no",        "Document No")}
          ${th("date",          "Date")}
          ${th("status",        "Status")}
          ${th("created_by",    "By")}
          ${th("item_code",     "Item Code")}
          ${th("item_name",     "Item Name", "text-wrap")}
          ${th("requested_qty", "Req. Qty", "text-right")}
          ${th("issued_qty",    "Iss. Qty",  "text-right")}
          ${th("uom",           "UOM")}
        </tr>
      </thead>
      <tbody class="mref-body">${rows_html}</tbody>
    </table>
  </div>
</div>`;
}

// ── interactivity ─────────────────────────────────────────────────────────────
function _mref_init($wrap, total) {
    const $tbody = $wrap.find(".mref-body");
    const $count = $wrap.find(".mref-count");

    function recount() {
        const n = $tbody.find("tr[data-row]:visible").length;
        $count.text(`${n} / ${total} rows`);
    }
    recount();

    // live filter
    $wrap.find(".mref-search").on("input", function () {
        const q = this.value.toLowerCase();
        $tbody.find("tr[data-row]").each(function () {
            $(this).toggle(!q || $(this).text().toLowerCase().includes(q));
        });
        recount();
    });

    // column sort
    let _sort_col = null, _sort_asc = true;
    $wrap.find("th[data-col]").on("click", function () {
        const col = $(this).data("col");
        _sort_asc = (_sort_col === col) ? !_sort_asc : true;
        _sort_col = col;
        const ci = $(this).index();

        const sorted = $tbody.find("tr[data-row]").toArray().sort((a, b) => {
            const va = $(a).find("td").eq(ci).text().trim();
            const vb = $(b).find("td").eq(ci).text().trim();
            const na = parseFloat(va.replace(/,/g, "")), nb = parseFloat(vb.replace(/,/g, ""));
            const cmp = (!isNaN(na) && !isNaN(nb))
                ? na - nb
                : va.localeCompare(vb, undefined, { numeric: true });
            return cmp * (_sort_asc ? 1 : -1);
        });
        $tbody.empty().append(sorted);

        $wrap.find("th[data-col]").each(function () {
            const arrow = $(this).data("col") === col ? (_sort_asc ? " ▲" : " ▼") : "";
            $(this).text($(this).text().replace(/ [▲▼]$/, "") + arrow);
        });
    });

    // refresh button
    $wrap.find(".mref-refresh").on("click", function () {
        const frm = cur_frm;
        if (frm) _mref_render(frm);
    });
}
"""


# ---------------------------------------------------------------------------
# Custom fields
# ---------------------------------------------------------------------------

def _add_custom_fields():
    section = "msjr_material_references_section"
    html    = "material_references_html"

    if not frappe.db.exists("Custom Field", f"Machine Shop Job Request-{section}"):
        frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "Machine Shop Job Request",
            "fieldname": section,
            "label": "Material References",
            "fieldtype": "Section Break",
            "insert_after": "amended_from",
            "collapsible": 1,
        }).insert(ignore_permissions=True)
        print(f"Created: {section}")
    else:
        print(f"Exists: {section}")

    if not frappe.db.exists("Custom Field", f"Machine Shop Job Request-{html}"):
        frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "Machine Shop Job Request",
            "fieldname": html,
            "label": "Material References",
            "fieldtype": "HTML",
            "insert_after": section,
        }).insert(ignore_permissions=True)
        print(f"Created: {html}")
    else:
        print(f"Exists: {html}")


# ---------------------------------------------------------------------------
# Client script
# ---------------------------------------------------------------------------

def _upsert_client_script():
    if frappe.db.exists("Client Script", SCRIPT_NAME):
        doc = frappe.get_doc("Client Script", SCRIPT_NAME)
        doc.script = SCRIPT_JS
        doc.enabled = 1
        doc.flags.ignore_permissions = True
        doc.save()
        print(f"Updated: {SCRIPT_NAME}")
    else:
        frappe.get_doc({
            "doctype": "Client Script",
            "name": SCRIPT_NAME,
            "dt": "Machine Shop Job Request",
            "view": "Form",
            "script": SCRIPT_JS,
            "enabled": 1,
        }).insert(ignore_permissions=True)
        print(f"Created: {SCRIPT_NAME}")

    # Sync fixture
    app_path = frappe.get_app_path("qcmc_logic")
    path = os.path.join(app_path, "fixtures", "client_script.json")
    with open(path) as f:
        scripts = json.load(f)
    existing = next((s for s in scripts if s.get("name") == SCRIPT_NAME), None)
    if existing:
        existing["script"] = SCRIPT_JS
        existing["enabled"] = 1
    else:
        scripts.append({
            "doctype": "Client Script",
            "name": SCRIPT_NAME,
            "dt": "Machine Shop Job Request",
            "view": "Form",
            "script": SCRIPT_JS,
            "enabled": 1,
        })
    with open(path, "w") as f:
        json.dump(scripts, f, indent=1, ensure_ascii=False)
    print("Fixture client_script.json synced.")


# ---------------------------------------------------------------------------

def run():
    _add_custom_fields()
    _upsert_client_script()
    frappe.db.commit()
    frappe.clear_cache(doctype="Machine Shop Job Request")
    print("Done.")
