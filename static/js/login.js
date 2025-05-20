/* Animador do campo de senha ----------------------------------------- */
const btn  = document.getElementById('reveal');
const box  = document.getElementById('pass');
const fake = document.getElementById('fakepass');

const isEmpty = str => !str.trim().length;

btn.addEventListener('click', () => {
    /* desenha ••• para o fakepass */
    fake.textContent = '•'.repeat(box.value.length);
    fake.classList.toggle('scan');
    btn.classList.toggle('open');
    box.classList.toggle('active');

    /* alterna visibilidade da senha */
    if (box.type === 'password') {
        box.type = 'text';
    } else {
        /* aguarda a animação antes de esconder novamente */
        setTimeout(() => (box.type = 'password'), 500);
    }
});

box.addEventListener('input', () => {
    /* habilita / desabilita o botão */
    if (isEmpty(box.value)) {
        btn.setAttribute('disabled', 'disabled');
    } else {
        btn.removeAttribute('disabled');
    }
});
