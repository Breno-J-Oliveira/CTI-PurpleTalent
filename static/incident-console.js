'use strict';
const consolePanel = document.querySelector('[data-incident-console]');
if (consolePanel) {
    const form = consolePanel.querySelector('form');
    const button = form.querySelector('button');
    const status = consolePanel.querySelector('[data-status]');
    const records = consolePanel.querySelector('[data-records]');
    const url = consolePanel.dataset.request;
    const timer = consolePanel.querySelector('[data-lab-time]');
    const deadline = performance.now() + Number(timer.dataset.remaining) * 1000;
    const clock = setInterval(() => {
        const minutes = Math.ceil(Math.max(0, deadline - performance.now()) / 60000);
        timer.textContent = minutes ? 'Tempo restante: ' + minutes + ' min' : 'Prazo do laboratório encerrado.';
        if (!minutes) clearInterval(clock);
    }, 1000);
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        button.disabled = true;
        records.textContent = '';
        status.textContent = 'Consultando a máquina virtual…';
        try {
            const request = await fetch(url, {method: 'POST', body: new FormData(form)});
            if (!request.ok) throw new Error();
            const {id} = await request.json();
            for (let attempt = 0; attempt < 15; attempt++) {
                await new Promise(resolve => setTimeout(resolve, 3000));
                const response = await fetch(url + '/' + id, {cache: 'no-store'});
                if (!response.ok) throw new Error();
                const result = await response.json();
                if (result.status === 'failed') throw new Error();
                if (result.status === 'completed') {
                    records.textContent = result.body;
                    status.textContent = 'Registros carregados.';
                    return;
                }
            }
            throw new Error();
        } catch {
            status.textContent = 'O ambiente não respondeu. Confira a disponibilidade e tente novamente.';
        } finally {
            button.disabled = false;
        }
    });
}
