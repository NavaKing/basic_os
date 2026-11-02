// Printable issue: the toolbar's button opens the browser's print dialog (which can also save a PDF).

document.getElementById('print_now')?.addEventListener('click', () => window.print());
// The print view is meant for paper: open the dialog straight away when asked (?print=1)
if (new URLSearchParams(location.search).has('print')) window.addEventListener('load', () => window.print());
