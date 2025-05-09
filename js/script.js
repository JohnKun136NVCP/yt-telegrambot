function createSakura() {
    const sakura = document.createElement('div');
    sakura.classList.add('sakura');
    document.querySelector('.sakura-background').appendChild(sakura);


    sakura.style.left = Math.random() * window.innerWidth + 'px';
    sakura.style.animationDuration = (Math.random() * 5 + 3) + 's'; 

    setTimeout(() => {
        sakura.remove();
    }, 8000);
}


setInterval(createSakura, 150);
