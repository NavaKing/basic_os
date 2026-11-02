// Backups window (opened from the tab bar): make, download, restore, delete and upload copies of the app's database.

import { esc, setStatus } from './utils.js';

function sizeText(bytes) {
    return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(bytes / 1024)) + ' KB';
}

function dateText(iso) {
    return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function renderList(list, backups) {
    if (!backups.length) {
        list.innerHTML = '<li class="empty-note empty-note--compact">No backups yet.</li>';
        return;
    }
    list.innerHTML = backups.map(b =>
        '<li class="backup-item' + (b.automatic ? ' backup-item--auto' : '') + '">' +
            '<div class="backup-item-text">' +
                '<div class="backup-item-label">' + esc(b.label_text) + '</div>' +
                '<div class="backup-item-meta">' + esc(dateText(b.created)) + ' &middot; ' + esc(sizeText(b.size)) + '</div>' +
            '</div>' +
            '<div class="backup-item-actions">' +
                '<a class="btn-secondary backup-action" href="/backups/' + encodeURIComponent(b.file) + '" download>Download</a>' +
                '<button type="button" class="btn-secondary backup-action" data-restore="' + esc(b.file) + '">Restore</button>' +
                '<button type="button" class="btn-secondary backup-action backup-action--delete" data-delete="' + esc(b.file) + '">Delete</button>' +
            '</div>' +
        '</li>').join('');
}

async function call(url, options, status) {
    const res = await fetch(url, options);
    const data = await res.json().catch(() => ({ error: 'HTTP ' + res.status }));
    if (data.error) setStatus(status, data.error, true);
    return data;
}

export function initBackups() {
    const dialog = document.getElementById('backup_dialog');
    const list = document.getElementById('backup_list');
    const status = document.getElementById('backup_status');
    const show = data => { if (data.backups) renderList(list, data.backups); };

    const open = async () => {
        setStatus(status, '');
        if (!dialog.open) dialog.showModal();
        show(await call('/backups', {}, status));
    };
    document.getElementById('backups_open').addEventListener('click', open);
    // ?backups opens the window directly
    if (new URLSearchParams(location.search).has('backups')) open();
    document.getElementById('backup_close').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });

    document.getElementById('backup_form').addEventListener('submit', async event => {
        event.preventDefault();
        const label = document.getElementById('backup_label');
        setStatus(status, 'Backing up...');
        const data = await call('/backups', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                              body: JSON.stringify({ label: label.value }) }, status);
        show(data);
        if (!data.error) {
            label.value = '';
            setStatus(status, 'Backup made.');
        }
    });

    list.addEventListener('click', async event => {
        const restore = event.target.closest('[data-restore]');
        const remove = event.target.closest('[data-delete]');
        if (restore) {
            if (!confirm('Restore this backup? Everything the app made since then is replaced. ' +
                         'Your current data is backed up first, so you can undo this.')) return;
            setStatus(status, 'Restoring...');
            const data = await call('/backups/' + encodeURIComponent(restore.dataset.restore) + '/restore', { method: 'POST' }, status);
            show(data);
            if (!data.error) {
                setStatus(status, 'Restored. Reloading...');
                setTimeout(() => location.reload(), 600);
            }
        } else if (remove) {
            if (!confirm('Delete this backup for good?')) return;
            show(await call('/backups/' + encodeURIComponent(remove.dataset.delete), { method: 'DELETE' }, status));
            setStatus(status, 'Backup deleted.');
        }
    });

    document.getElementById('backup_file').addEventListener('change', async event => {
        const file = event.target.files[0];
        event.target.value = '';
        if (!file) return;
        setStatus(status, 'Uploading ' + file.name + '...');
        const data = await call('/backups/upload', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file }, status);
        show(data);
        if (!data.error) setStatus(status, 'Uploaded. Press Restore on it to use it.');
    });
}
