'use strict';

const reservation = document.querySelector('[data-lab-reservation]:not([data-lab-idle])');
if (reservation) {
    const statusError = document.querySelector('[data-lab-status-error]');
    let lastMarkup = reservation.innerHTML.trim();
    let stopped = false;

    reservation.addEventListener('submit', () => { stopped = true; });

    async function refreshReservation() {
        if (stopped) return;
        try {
            const response = await fetch(reservation.dataset.labReservation, {cache: 'no-store'});
            if (!response.ok || response.redirected) throw new Error();
            const markup = (await response.text()).trim();
            if (!stopped && markup !== lastMarkup && !reservation.contains(document.activeElement)) {
                reservation.innerHTML = markup;
                lastMarkup = markup;
            }
            statusError.hidden = true;
        } catch {
            statusError.hidden = false;
        } finally {
            if (!stopped) setTimeout(refreshReservation, 5000);
        }
    }

    setTimeout(refreshReservation, 5000);
}
