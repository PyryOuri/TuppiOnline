# `project_target_v1`: projektin määräävä Tuppi-säännöstö

## Asema ja alkuperä

Tämä on `project_target_v1`-säännöstön suomenkielinen määrittely. Englanninkielinen
`project_target_v1.md` on ensisijainen tekninen määrittely, mutta tämän tekstin
tarkoitus on säilyttää projektin omistajan alkuperäinen suomalainen sanasto ja
sääntömerkitys täsmällisesti.

| Tieto | Arvo |
| --- | --- |
| Lähdetyyppi | Projektin omistajan sääntömäärittely |
| Määrittelyn päivä | 31.7.2026 |
| Alkuperäinen kieli | Suomi |
| Asema | Määräävä tässä projektissa |
| Suhde turnaussääntöihin | Perustuu perinteiseen/turnaustyyliseen Tuppeen, mutta sisältää tarkoituksellisia muutoksia |

Erillisiä fyysisiä näyttökortteja ei käytetä. Jokainen jako pelataan aina 13
tikkiin asti. Ottelussa käytetään jatkuvaa nousupistelaskua, kunnes toinen pari
saavuttaa vähintään 52 pistettä. Verkkolähteet ja `legacy_v9_unverified` eivät
syrjäytä tätä määrittelyä. Säännöstölle ei väitetä projektin ulkopuolista
virallista asemaa.

## Käsitteet

- Pelaajapaikat ovat kiinteässä järjestyksessä 0, 1, 2, 3 myötäpäivään.
- Joukkue 0 on paikat 0 ja 2. Joukkue 1 on paikat 1 ja 3.
- **Etukäsi** on jakajasta seuraava pelaaja myötäpäivään.
- **Näyttö** sisältää yhden omasta kädestä julkisesti näytetyn kortin ja
  yksiselitteisen sisäisen sopimusilmoituksen.
- **Ramaaja** on ensimmäinen RAMIn ilmoittanut pelaaja.
- **Nousussa** tai **ylhäällä** on se ainoa joukkue, jolla on positiivinen
  ottelupistemäärä.
- **Pöydässä** tarkoittaa tilannetta 0–0.
- **Ramin ryöstö** tapahtuu, kun ramaajan joukkue saa enintään kuusi tikkiä.
- **Tuppeen paneminen** on perinteinen ilmaus, mutta sillä ei ole tässä
  säännöstössä pistekaavoista erillistä lisävaikutusta.

## Pelaajat, kortit ja parit

Pelissä on neljä pelaajaa. Käytössä on tavallinen 52 kortin pakka, joka jaetaan
kokonaan: jokainen saa 13 korttia. Hertta ja ruutu ovat punaisia; risti ja pata
mustia. Arvojärjestys pienimmästä suurimpaan on 2, 3, 4, 5, 6, 7, 8, 9, 10,
jätkä, rouva, kuningas ja ässä. Valttia ei ole.

Ohjelmallinen maajärjestys hertta, ruutu, risti, pata on vain tallennusmuoto;
se ei anna maille pelillistä arvojärjestystä.

## Jakaja ja etukäsi

Ottelun suorittaja antaa alkujakajan nimenomaisesti. Mahdollinen satunnainen
valinta kuuluu suorittajalle eikä sääntöytimeen.

```text
etukäsi = (jakaja + 1) modulo 4
seuraava jakaja valmiin jaon jälkeen = (jakaja + 1) modulo 4
```

Ei-päättyneen ottelun seuraava jako alkaa uudella etukädellä. Päättyneen
ottelun jälkeen uutta jakoa ei aloiteta.

## Näyttö ja pelimuodon valinta

Pelimuodot ovat RAMI, jossa joukkueet pyrkivät saamaan tikkejä, ja NOLO, jossa
joukkueet pyrkivät välttämään tikkejä.

Jokaisessa toteutuneessa näyttötoimessa pelaaja näyttää yhden omassa kädessään
olevan kortin. Näyttö alkaa etukädestä ja etenee myötäpäivään. Näyttökelpoisia
arvoja ovat vain 3, 4, 5, 6, 7, 8 ja 9. Arvot 2, 10, jätkä, rouva, kuningas ja
ässä eivät normaalisti kelpaa näyttöön. RAMIn normaaliväri on punainen ja NOLOn
normaaliväri musta.

Valinta ratkaistaan aina seuraavassa etusijajärjestyksessä:

1. Jos kädessä on vähintään yksi ilmoitetun pelimuodon normaalivärinen
   näyttökelpoinen kortti, on näytettävä jokin juuri näistä korteista. Sanallista
   ilmoitusta ei vaadita.
2. Jos normaaliväristä näyttökelpoista korttia ei ole, mutta kädessä on jokin
   näyttökelpoinen kortti, saa näyttää minkä tahansa näyttökelpoisen kortin.
   Pelimuoto ilmoitetaan sanallisesti, ja nimenomainen ilmoitus ohittaa kortin
   värin.
3. Jos kädessä ei ole yhtään näyttökelpoista korttia, on silti näytettävä yksi
   kortti omasta kädestä. Mikä tahansa käden kortti kelpaa, ja pelimuoto
   ilmoitetaan sanallisesti.

Kenttä `verbal_required` johdetaan kädestä, näytetystä kortista ja ilmoitetusta
pelimuodosta. Pelaaja tai ohjelma ei saa valita sen arvoa vapaasti. Kolmannessa
tapauksessa sanallinen ilmoitus vaaditaan silloinkin, kun epäsopivan arvon
kortti sattuu olemaan normaalivärinen. Ohjelmallinen `ShowAction`-tarkistus
vaatii koko 13 kortin käden, koska näyttö tapahtuu ennen tikkipeliä, mutta
julkiseen toimintoon ei tallenneta koko kättä.

Näytetty kortti paljastetaan kaikille, mutta se jää käteen. Sitä ei poisteta,
varata eikä muuteta, ja sen saa myöhemmin pelata tavalliseen tapaan.

Näyttö päättyy heti ensimmäiseen RAMI-ilmoitukseen. Ilmoittajasta tulee
ramaaja, eivätkä hänen jälkeensä tulevat pelaajat enää näytä. Jos kaikki neljä
järjestyksessä olevaa näyttöä ovat NOLOja, pelimuoto on NOLO eikä ramaajaa ole.
Alle neljän NOLO-ilmoituksen sarja on keskeneräinen. Väärä järjestys,
kaksoisnäyttö tai RAMIn jälkeinen näyttö hylätään.

## Ensimmäinen aloittaja

- NOLOssa etukäsi aloittaa ensimmäisen tikin.
- RAMIssa ramaajaa näyttöjärjestyksessä välittömästi edeltävä pelaaja aloittaa:
  `(ramaaja - 1) modulo 4`.

Kun etukäsi ramaa, jakaja aloittaa.

## Tikkipeli ja jaon pituus

Aloittaja saa pelata minkä tahansa kädessään olevan kortin. Muiden on
tunnustettava aloitusmaata, jos sitä on kädessä. Maata vailla oleva saa pelata
minkä tahansa käden kortin. Virheellinen kortti hylätään eikä sitä vaihdeta
automaattisesti toiseksi.

Tikissä pelataan täsmälleen neljä korttia myötäpäivään. Aloitetun maan suurin
kortti voittaa. Muun maan kortti, edes ässä, ei voi voittaa. Tikin voittaja
aloittaa seuraavan tikin.

Valmiissa jaossa on aina 13 täyttä tikkiä ja kaikki 52 korttia pelataan tasan
kerran. Jakoa ei katkaista, vaikka tulos, nousun putoaminen tai ottelun tuleva
päättyminen olisi jo varma. Pisteet lasketaan vasta 13. tikin jälkeen.

## NOLO-pisteet

Vähemmän tikkejä saanut joukkue voittaa. Tasan ei voida päätyä, koska tikkejä
on 13.

```text
pisteet = 4 × (7 - voittajan tikit)
```

| Voittajan tikit | Pisteet |
| ---: | ---: |
| 6 | 4 |
| 5 | 8 |
| 4 | 12 |
| 3 | 16 |
| 2 | 20 |
| 1 | 24 |
| 0 | 28 |

## RAMI-pisteet ja ramin ryöstö

Ramaajan pari on ilmoittava joukkue. Jos se saa vähintään seitsemän tikkiä, se
voittaa:

```text
pisteet = 4 × (ramaajan joukkueen tikit - 6)
```

Seitsemästä kolmeentoista tikkiin pisteet ovat järjestyksessä 4, 8, 12, 16,
20, 24 ja 28.

Jos ramaajan joukkue saa enintään kuusi tikkiä, vastustaja voittaa ramin
ryöstöllä:

```text
pisteet = 8 × (vastustajan tikit - 6)
```

Kun ramaajan joukkue saa 6, 5, 4, 3, 2, 1 tai 0 tikkiä, vastustaja saa jaosta
vastaavasti 8, 16, 24, 32, 40, 48 tai 56 pistettä ennen ottelun
noususiirtymän soveltamista.

## Nousupisteet ja ottelun päättyminen

Kelvollisia tilanteita ovat 0–0, positiivinen–0 ja 0–positiivinen. Molemmat
joukkueet eivät saa olla yhtä aikaa positiivisilla pisteillä. Positiivinen
joukkue on nousussa eli ylhäällä; toinen on alhaalla.

- Kun ollaan pöydässä 0–0, jaon voittaja saa jaon pisteet ja nousee ylös.
- Kun ylhäällä oleva joukkue voittaa, pisteet lisätään sen entisiin pisteisiin.
- Kun alhaalla oleva joukkue voittaa, ylhäällä olevan pisteet pyyhitään ja
  tulos on 0–0. Alhaalla oleva ei saa tämän jaon pisteitä itselleen.

Nollaus koskee myös 56 pisteen ramin ryöstöä. Esimerkiksi tilanteessa 20–0
Joukkueen 1 tällainen voitto tekee tulokseksi 0–0, ei 0–56.

Ottelu päättyy, kun ylhäällä oleva joukkue saavuttaa **vähintään 52 pistettä**.
Täsmälleen 52 ei ole pakollinen: 48 + 4 = 52 ja 48 + 8 = 56 päättävät molemmat
ottelun. Päättyneeseen otteluun ei sovelleta enää uutta pistesiirtymää.

Esimerkkejä:

- Pöydässä 0–0 Joukkueen 1 kahdeksan pisteen jakovoitto tekee tulokseksi 0–8.
- Tilanteessa 20–0 Joukkueen 1 kahdeksan pisteen jakovoitto pudottaa nousun ja
  tekee tulokseksi 0–0.
- Tilanteessa 48–0 Joukkueen 0 neljän pisteen voitto tekee tulokseksi 52–0 ja
  päättää ottelun.
- Tilanteessa 48–0 Joukkueen 0 kahdeksan pisteen voitto tekee tulokseksi 56–0
  ja päättää ottelun.
- Tilanteessa 0–48 Joukkueen 1 kahdeksan pisteen voitto tekee tulokseksi 0–56
  ja päättää ottelun.
- Tilanteessa 20–0 Joukkueen 1 56 pisteen ramin ryöstö tekee tulokseksi 0–0.

Ottelussa ei ole kiinteää jakomäärää, seitsemän tikin jälkeistä jaon
katkaisua eikä automaattista pisteiden siirtoa alhaalla olevalle joukkueelle.

## Virhetilanteet ja reunatapaukset

- Paikan on oltava kokonaisluku 0–3; totuusarvoja ei hyväksytä numeroina.
- Kädessä olematonta korttia ei saa näyttää eikä pelata.
- Näyttövalinnan etusijatasoa ei saa ohittaa.
- Keskeneräistä NOLO-sarjaa ei tulkita ratkaistuksi.
- Jaon joukkuekohtaisten tikkien on oltava ei-negatiivisia ja summaltaan 13
  ennen pisteytystä.
- Alle 13 tikin jako ei ole valmis, vaikka voittaja olisi jo varma.
- Negatiivinen ottelupiste tai kahden yhtä aikaa positiivisen joukkueen tila on
  virheellinen.
- Sääntöfunktiot hylkäävät virheen näkyvästi; ne eivät käytä hiljaista
  oletusarvoa tai korvaavaa siirtoa.

## Erot jäädytettyyn `legacy_v9_unverified`-artefaktiin

- Legacyn oletus kieltää näytöstä arvot 2, jätkä, rouva ja kuningas, joten 10 ja
  ässä jäävät normaalisti sallituiksi. Tässä säännöstössä vain 3–9 kelpaavat.
- Legacy pyytää kaikkien neljän valinnat ennen paljastamista; RAMI katkaisee
  vain paljastamisen. Tässä säännöstössä myös toimintojen kerääminen loppuu
  heti RAMIin.
- Legacyn sanallisessa näytössä kortti voi puuttua. Tässä jokainen toteutunut
  näyttö sisältää oman käden kortin, joka paljastetaan.
- Tässä pelimuoto ilmoitetaan aina sisäisesti nimenomaisena arvona ja kortti
  tarkistetaan kolmiportaista sääntöä vasten. Legacyn menettely riippuu
  pelaajatyypistä.
- Molemmissa näytetty käsikortti säilyy, pelataan 13 tikkiä, käytetään samoja
  perusjohtaja- ja jakopistekaavoja, kierretään jakajaa myötäpäivään ja
  tavoitellaan jatkuvassa nousussa vähintään 52 pistettä. Projektisäännön
  auktoriteetti tulee silti omistajan määrittelystä, ei legacysta.
- Legacyn suora pistelasku (flat scoring), jossa molemmat joukkueet voivat
  kerryttää pisteitä, muuttuvat havainto-oliot, yhteinen
  satunnaislähde, hiljaiset oletukset ja laittoman siirron korvaaminen eivät
  kuulu `project_target_v1`:een.
- Legacy aloittaa sisäisesti jakajasta 0; tässä suorittajan on annettava
  alkujakaja.

## Versiointiperiaate

Kun `project_target_v1`:llä on ajettu tallennettuja kokeita, tunniste on
muuttumaton. Pelikäyttäytymiseen vaikuttava muutos vaatii uuden tunnisteen sekä
uuden konfiguraation, toteutuksen, esimerkit ja normatiiviset testit. Pelkkä
merkitystä muuttamaton toimituksellinen korjaus voidaan tehdä saman tunnisteen
alla, mutta se dokumentoidaan. Tulostietue säilyttää aina käytetyn tarkan
säännöstötunnisteen.
