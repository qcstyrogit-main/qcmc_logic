const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

// Exercise the installed Frappe renderer: it passes formatter output to
// jQuery as HTML to measure text. Bare text is interpreted as a CSS selector.
const context = {
    frappe: {
        provide: () => {}, views: { BaseList: class {} }, listview_settings: {},
        boot: {}, model: { is_numeric_field: () => false }, is_mobile: () => false,
        utils: {
            escape_html: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;'),
            get_form_link: (type, name, html, label) => `<a href="/${type}/${name}">${label}</a>`,
        },
    },
    __: (text, args = []) => text.replace('{0}', args[0]),
    $: html => {
        assert(!html || html.trim().startsWith('<'),
            'List formatter output must be HTML; plain text is parsed as a selector');
        return { text: () => html.replace(/<[^>]*>/g, '') };
    },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('../frappe/frappe/public/js/frappe/list/list_view.js', 'utf8')
    .replace(/^import .*;\n/gm, ''), context);
vm.runInContext(fs.readFileSync('qcmc_logic/qcmc_logics/doctype/storage_allocation/storage_allocation_list.js', 'utf8'), context);
const list = Object.create(context.frappe.views.ListView.prototype);
list.settings = context.frappe.listview_settings['Storage Allocation'];
list.link_field_title_fields = {};
list.column_max_widths = {};
const column = { type: 'Field', df: { fieldname: 'source_document', fieldtype: 'Dynamic Link', label: 'Source Document' } };
const rows = [
    { source_doctype: 'Purchase Receipt', source_document: 'WRR-1', source_document_count: 1 },
    { source_doctype: 'Stock Entry', source_document: 'STE-1', source_document_count: 1 },
    { source_doctype: 'Stock Entry', source_document: null, source_document_count: 2 },
    { source_doctype: 'Stock Entry', source_document: 'STE-2', source_document_count: 1 },
    { source_document: null, source_document_count: 0 },
];
const rendered = rows.map(row => list.get_column_html(column, row, false));
assert.equal(rendered.length, 5);
assert(rendered[2].includes('Multiple documents (2)'));
assert(rendered[3].includes('STE-2'));
console.log('Storage Allocation list renders single, multiple, and missing sources without stopping');
