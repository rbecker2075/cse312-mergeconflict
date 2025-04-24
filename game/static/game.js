// Get the game container's dimensions
const container = document.querySelector('.game-container');
const containerWidth = container.clientWidth;
const containerHeight = container.clientHeight;

// World dimensions based on 9x9 grid of 1920x1080 background
const bgWidth = 1920;
const bgHeight = 1080;
const worldWidth = bgWidth * 9;
const worldHeight = bgHeight * 9;

const config = {
  type: Phaser.AUTO,
  width: containerWidth,
  height: containerHeight,
  physics: {
    default: 'arcade',
    arcade: {
      debug: false
    }
  },
  scene: {
    preload: preload,
    create: create,
    update: update
  }
};

const game = new Phaser.Game(config);

let player;
let cursors;
const playerSpeed = 200;
const playerInitialSize = 0.15;
let socket;
let otherPlayers = {};

function preload() {
  this.load.image('playerSprite', '/game/static/assets/PurplePlanet.png');
  this.load.image('background', '/game/static/assets/Background.png');
}

function create() {
  this.add.tileSprite(0, 0, worldWidth, worldHeight, 'background').setOrigin(0, 0);

  this.physics.world.setBounds(0, 0, worldWidth, worldHeight);

  player = this.physics.add.sprite(worldWidth / 2, worldHeight / 2, 'playerSprite');
  player.setOrigin(0.5, 0.5);
  player.setScale(playerInitialSize);
  player.setCollideWorldBounds(true);
  player.setDepth(1);

  cursors = this.input.keyboard.addKeys('W,A,S,D');

  this.cameras.main.setBounds(0, 0, worldWidth, worldHeight);
  this.cameras.main.startFollow(player, true, 0.08, 0.08);
  socket = new WebSocket(`ws://${location.host}/ws/game`);

  socket.addEventListener("open", () => {
    console.log("Connected to server");
  });

  socket.addEventListener("message", (event) => {
    const data = JSON.parse(event.data);

    if (data.type === "players") {
      for (const [id, info] of Object.entries(data.players)) {
        if (id === socket.id) continue;

        if (!otherPlayers[id]) {
          const other = this.add.sprite(info.x, info.y, 'playerSprite').setScale(playerInitialSize);
          other.setDepth(1);

          // Add power text
          const powerText = this.add.text(0, 0, info.power, {
            fontSize: '16px',
            color: '#fff',
            align: 'center'
          });
          powerText.setOrigin(0.5, 0.5);

          // Position the power text above the player sprite
          powerText.setPosition(other.x, other.y - other.height / 2 - 10); // Adjust position relative to sprite

          otherPlayers[id] = { sprite: other, powerText: powerText, power: info.power };
        } else {
          otherPlayers[id].sprite.x = info.x;
          otherPlayers[id].sprite.y = info.y;
          otherPlayers[id].power = info.power;

          // Update power text
          otherPlayers[id].powerText.setText(info.power);
          otherPlayers[id].powerText.setPosition(info.x, info.y - otherPlayers[id].sprite.height / 2 - 10); // Keep it above the player
        }
      }
    } else if (data.type === "id") {
      socket.id = data.id;
      socket.connection_id = data.connection_id;  // Store the connection_id
    } else if (data.type === "remove") {
      if (otherPlayers[data.id]) {
        otherPlayers[data.id].sprite.destroy();
        otherPlayers[data.id].powerText.destroy();
        delete otherPlayers[data.id];
      }
    }
  });

  this.time.addEvent({
    delay: 50,
    loop: true,
    callback: () => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
          x: player.x,
          y: player.y
        }));
      }
    }
  });
}

function update(time, delta) {
  const dt = delta / 1000;

  let moveX = 0;
  let moveY = 0;

  if (cursors.A.isDown) moveX = -1;
  else if (cursors.D.isDown) moveX = 1;
  if (cursors.W.isDown) moveY = -1;
  else if (cursors.S.isDown) moveY = 1;

  const moveVector = new Phaser.Math.Vector2(moveX, moveY).normalize();
  player.body.setVelocity(moveVector.x * playerSpeed, moveVector.y * playerSpeed);
}