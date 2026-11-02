// Press room (Coaches tab): ask our head coach or a coordinator a question and keep the week's transcript.

import { esc, setStatus, postJSON } from './utils.js';

function render(list, transcript) {
    list.innerHTML = transcript.length ? transcript.slice().reverse().map(t =>
        '<li class="press-qa">' +
            '<p class="press-q"><span>Q</span>' + esc(t.question) + '</p>' +
            '<div class="press-a">' +
                '<span class="headshot">' + (t.portrait ? '<img src="' + esc(t.portrait) + '" alt="">' : '') + '</span>' +
                '<div><div class="press-who">' + esc(t.speaker) + ' <small>' + esc(t.title) + '</small></div>' +
                '<p>&ldquo;' + esc(t.answer) + '&rdquo;</p></div>' +
            '</div>' +
        '</li>').join('') : '<li class="mag-empty">No questions yet this week.</li>';
}

export function initPresser() {
    const form = document.getElementById('press_form');
    if (!form) return;
    const list = document.getElementById('press_transcript');
    const status = document.getElementById('press_status');
    const question = document.getElementById('press_question');
    const submit = document.getElementById('press_submit');
    const suggest = document.getElementById('press_suggest');
    const suggestions = document.getElementById('press_suggestions');
    render(list, JSON.parse(document.getElementById('press_data').textContent));

    form.addEventListener('submit', async event => {
        event.preventDefault();
        const role = form.closest('.press-room').querySelector('input[name="press_role"]:checked').value;
        submit.disabled = true;
        setStatus(status, 'Waiting for an answer...');
        try {
            const data = await postJSON('/presser', { role, question: question.value });
            if (data.error) throw new Error(data.error);
            render(list, data.transcript);
            question.value = '';
            setStatus(status, '');
        } catch (err) {
            setStatus(status, String(err.message || err), true);
        } finally {
            submit.disabled = false;
        }
    });
    // Enter asks; Shift+Enter adds a line
    question.addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
    });

    suggest.addEventListener('click', async () => {
        suggest.disabled = true;
        setStatus(status, 'Thinking up questions...');
        try {
            const data = await postJSON('/presser/questions');
            if (data.error) throw new Error(data.error);
            suggestions.innerHTML = data.questions.map(q => '<button type="button" class="press-chip">' + esc(q) + '</button>').join('');
            suggestions.querySelectorAll('.press-chip').forEach(chip => chip.addEventListener('click', () => {
                question.value = chip.textContent;
                question.focus();
            }));
            setStatus(status, data.questions.length ? 'Pick one, edit it if you like, and ask.' : 'No questions came back. Try again.');
        } catch (err) {
            setStatus(status, String(err.message || err), true);
        } finally {
            suggest.disabled = false;
        }
    });

    document.getElementById('press_clear').addEventListener('click', async () => {
        if (!confirm("Clear this week's press conference?")) return;
        const data = await (await fetch('/presser', { method: 'DELETE' })).json();
        render(list, data.transcript || []);
        suggestions.innerHTML = '';
    });
}
