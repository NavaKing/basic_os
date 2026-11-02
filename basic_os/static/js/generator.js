// Hub generator button: writes the dispatch, tweets and storyline chapters, and renders the photos.

import { postJSON, setStatus } from './utils.js';

const POLL_MS = 1500;

/** onResult(data) receives the /generate response so each tab can re-render. */
export function initGenerator(onResult) {
    const button = document.getElementById('generate_btn');
    const status = document.getElementById('generator_status');
    const bar = document.getElementById('generator_progress');

    button.addEventListener('click', async () => {
        button.disabled = true;
        setStatus(status, 'Starting...');
        // Poll the server's progress while /generate runs
        const timer = setInterval(async () => {
            try {
                const p = await (await fetch('/generate/progress')).json();
                if (!p.running) return;
                setStatus(status, 'Step ' + p.number + ' of ' + p.total + ': ' + p.step + (p.detail ? ' (' + p.detail + ')' : '') + '... ' + p.elapsed + 's');
                bar.max = p.total;
                bar.value = Math.max(0, p.number - 1);
            } catch { /* keep waiting */ }
        }, POLL_MS);
        bar.hidden = false;
        try {
            const data = await postJSON('/generate');
            onResult(data);
            // /generate returns the new story on success, or an error message it didn't save
            const saved = (data.past_stories || []).some(story => story.generated_text === data.text);
            setStatus(status, saved ? 'Done: new dispatch, ' + (data.tweets || []).length + ' posts and photos are ready.' : data.text, !saved);
        } catch (err) {
            setStatus(status, 'Request failed: ' + err, true);
        } finally {
            clearInterval(timer);
            bar.hidden = true;
            button.disabled = false;
        }
    });
}
