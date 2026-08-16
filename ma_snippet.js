// Metal Archives - buscar genero de cada banda de la agenda de Metal-Daze.
// Pegar en la consola de Firefox ESTANDO en una pestana de metal-archives.com.
(async () => {
  const QUERIES = ["DISLEPSIA", "NEPAL", "WERKEN", "SPARTA", "PENTAGRAM", "FELIX MARTIN", "SONNE LICHT", "Hermetica", "ANGRA", "Rata Blanca", "ENTROPHIA", "UNDERCROFT", "STEELBALLS", "Queen", "MEMPHIS MAY FIRE", "BLESSTHEFALL", "SANCTUARY", "Kiss", "DIES IRAE", "DARLOTODO", "El Reloj", "BLOODBATH", "NERVO CHAOS", "THE HAUNTED", "Racer X", "CELESTE", "Led Zeppelin", "Magnos", "V8", "RITUAL DE BRUJAS", "AL DI MEOLA", "HELLOWEEN", "AZEROTH", "Misfits", "TOE", "LIVE", "SOUL ASYLUM", "LEFT TO DIE", "REQUIEM FOR EDEN", "KAMIKAZE", "LETHAL", "MAD", "LANDMVRKS", "OLD MAN'S CHILD", "V.I.D.A.", "Aerosmith", "CYNARA", "SONATA ARCTICA", "Nightwish", "HIGH ON FIRE", "SEPULTURA", "SATURNUS", "Backyard Babies", "DIE TOTEN HOSEN", "Jason", "Bertoncelli", "CABRAL", "LÖRIHEN", "NUM", "AMORPHIS", "BETWEEN THE BURIED AND ME", "GRUESOME", "Kamelot", "HELKER", "MORTIIS", "POSER", "AFTER FOREVER", "BETO VAZQUEZ INFINITY", "HELLBUTCHER", "IRON MAIDEN", "LA H NO MURIÓ", "ALTER BRIDGE", "FIT FOR A KING", "ZAKK SABBATH", "APOCALYPTICA", "MALEVOLENT CREATION", "MYSTIC CIRCLE", "A SKYLIT DRIVE", "Almafuerte", "Dethklok", "SIX FEET UNDER", "H2O", "BENEDICTION", "FISHBONE", "A WILHELM SCREAM", "OPETH", "DEF LEPPARD", "EXTREME", "Labyrinth", "HORCAS", "SOCIAL DISTORTION", "ILL NIÑO", "NATAS", "NOCTURNAL DEPRESSION", "WARHAMMER", "OPERA IX", "John 5", "Marilyn Manson", "Marty Friedman", "Megadeth", "Cacophony", "SARATOGA", "GODSPEED YOU! BLACK EMPEROR", "POGROM", "ZZ TOP", "MY DYING BRIDE", "NICO BORIE", "A PERFECT CIRCLE", "VIRTHUAL", "BALLES", "ARHIMAN", "Tarja", "TESTAMENT", "MUNICIPAL WASTE", "IMMOLATION", "Babymetal", "RATA BLANCA", "Doyle", "DYING FETUS", "FOSSILIZATION", "MYRATH", "YOUTH OF TODAY", "SLAUGHTER TO PREVAIL", "DEEP PURPLE", "SLAYER", "KREATOR", "AVERNAL", "Delain", "ELLENDE", "THYRFING", "LUCIFERIAN", "AVATAR", "Queensryche", "RUSH", "HELLRIPPER", "Blaze Bayley", "Wolfsbane", "CRASHDÏET", "MORTIFICATION", "ALCEST", "FOO FIGHTERS", "ANTIMATTER", "ELEINE", "EPICA", "RHAPSODY", "QUIET RIOT", "RHAPSODY OF FIRE", "MASTERPLAN", "SOEN", "THE CRUEL INTENTIONS"];
  const out = {};
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  console.log('Arrancando: ' + QUERIES.length + ' consultas, ~' + Math.ceil(QUERIES.length * 0.45) + 's.');
  for (let i = 0; i < QUERIES.length; i++) {
    const q = QUERIES[i];
    try {
      const res = await fetch(
        '/search/ajax-band-search/?field=name&query=' + encodeURIComponent(q),
        { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'include' }
      );
      out[q] = res.ok ? (await res.json()).aaData : ('HTTP ' + res.status);
    } catch (e) {
      out[q] = 'ERR ' + e.message;
    }
    if ((i + 1) % 20 === 0) console.log((i + 1) + '/' + QUERIES.length);
    await sleep(400);
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], { type: 'application/json' }));
  a.download = 'ma-genres.json';
  document.body.appendChild(a); a.click(); a.remove();
  console.log('LISTO. ' + Object.keys(out).length + ' consultas. Se descargo ma-genres.json');
})();
