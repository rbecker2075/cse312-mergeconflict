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
const playerSpeed = 400;
const playerInitialSize = 0.15;
let socket;
let otherPlayers = {};
let playerPower = 0;
let playerPowerText;
let timerText;
let foodInstances = {};  // Store food sprites

// Function to setup WebSocket listeners
function setupSocketListeners() {
  socket.addEventListener("open", () => {
    console.log("Connected to server");
  });

  socket.addEventListener("close", () => {
    console.log("Disconnected from server");
  });

  socket.addEventListener("error", (error) => {
    console.error("WebSocket error:", error);
  });

  socket.addEventListener("message", handleSocketMessage);
}

// Function to handle socket messages
function handleSocketMessage(event) {
  const data = JSON.parse(event.data);
  const scene = game.scene.scenes[0];

  if (data.type === "players") {
    // Update timer
    const minutes = Math.floor(data.time_remaining / 60);
    const seconds = Math.floor(data.time_remaining % 60);
    timerText.setText(`${minutes}:${seconds.toString().padStart(2, '0')}`);

    // Update food positions
    if (data.food) {
      // Remove food that's no longer in the list
      for (const foodId in foodInstances) {
        if (!data.food.some(f => f.id === foodId)) {
          foodInstances[foodId].destroy();
          delete foodInstances[foodId];
        }
      }
      
      // Add new food
      for (const food of data.food) {
        if (!foodInstances[food.id]) {
          const foodSprite = scene.add.sprite(food.x, food.y, 'food').setScale(0.1);
          foodSprite.setDepth(1);
          foodInstances[food.id] = foodSprite;
        }
      }
    }

    for (const [id, info] of Object.entries(data.players)) {
      if (id === socket.id) {
        // Update local player's power
        playerPower = info.power;
        playerPowerText.setText(playerPower.toString());
        continue;
      }

      if (!otherPlayers[id]) {
        const other = scene.add.sprite(info.x, info.y, 'playerSprite').setScale(playerInitialSize);
        other.setDepth(1);

        // Add power text
        const powerText = scene.add.text(0, 0, info.power, {
          fontSize: '16px',
          color: '#ffffff',
          align: 'center',
          backgroundColor: '#000000',
          padding: { x: 8, y: 4 },
          stroke: '#000000',
          strokeThickness: 4
        });
        powerText.setOrigin(0.5, 0.5);
        powerText.setPosition(other.x, other.y);
        powerText.setDepth(2);

        // Add username text
        const usernameText = scene.add.text(0, 0, info.username || 'Guest', {
          fontSize: '8px',
          color: '#ffffff',
          align: 'center',
          backgroundColor: '#000000',
          padding: { x: 8, y: 4 },
          stroke: '#000000',
          strokeThickness: 4
        });
        usernameText.setOrigin(0.5, 0.5);
        usernameText.setPosition(other.x, other.y - 30);
        usernameText.setDepth(2);

        otherPlayers[id] = { 
          sprite: other, 
          powerText: powerText, 
          usernameText: usernameText,
          power: info.power 
        };
      } else {
        otherPlayers[id].sprite.x = info.x;
        otherPlayers[id].sprite.y = info.y;
        otherPlayers[id].power = info.power;

        // Update power text
        otherPlayers[id].powerText.setText(info.power);
        otherPlayers[id].powerText.setPosition(info.x, info.y);
        
        // Update username text
        otherPlayers[id].usernameText.setText(info.username || 'Guest');
        otherPlayers[id].usernameText.setPosition(info.x, info.y - 30);
      }
    }
  } else if (data.type === "id") {
    socket.id = data.id;
    // Update initial timer
    const minutes = Math.floor(data.time_remaining / 60);
    const seconds = Math.floor(data.time_remaining % 60);
    timerText.setText(`${minutes}:${seconds.toString().padStart(2, '0')}`);

    // Create initial food
    if (data.food) {
      for (const food of data.food) {
        const foodSprite = scene.add.sprite(food.x, food.y, 'food').setScale(0.1);
        foodSprite.setDepth(1);
        foodInstances[food.id] = foodSprite;
      }
    }
  } else if (data.type === "food_update") {
    // Remove collected food
    for (const foodId of data.removed_food) {
      if (foodInstances[foodId]) {
        foodInstances[foodId].destroy();
        delete foodInstances[foodId];
      }
    }
  } else if (data.type === "game_over") {
    // Create winner text above the player
    const winnerText = scene.add.text(player.x, player.y - 60, 
      `Winner is ${data.winner}`, {
      fontSize: '32px',
      color: '#ffffff',
      align: 'center',
      backgroundColor: '#000000',
      padding: { x: 20, y: 10 },
      stroke: '#000000',
      strokeThickness: 4
    });
    winnerText.setOrigin(0.5);
    winnerText.setDepth(100);

    // Update winner text position with player
    scene.time.addEvent({
      delay: 10,
      loop: true,
      callback: () => {
        winnerText.setPosition(player.x, player.y - 60);
      }
    });

    // Remove winner text after 5 seconds
    setTimeout(() => {
      winnerText.destroy();
    }, 5000);
  } else if (data.type === "game_reset") {
    // Reset local player's power
    playerPower = 1;
    playerPowerText.setText('1');
    
    // Reset player position
    player.x = worldWidth / 2;
    player.y = worldHeight / 2;
    
    // Update timer with full duration
    const minutes = Math.floor(game_duration / 60);
    const seconds = Math.floor(game_duration % 60);
    timerText.setText(`${minutes}:${seconds.toString().padStart(2, '0')}`);

    // Clear existing food
    for (const foodId in foodInstances) {
      foodInstances[foodId].destroy();
    }
    foodInstances = {};

    // Create new food
    if (data.food) {
      for (const food of data.food) {
        const foodSprite = scene.add.sprite(food.x, food.y, 'food').setScale(0.1);
        foodSprite.setDepth(1);
        foodInstances[food.id] = foodSprite;
      }
    }
  } else if (data.type === "remove") {
    if (otherPlayers[data.id]) {
      otherPlayers[data.id].sprite.destroy();
      otherPlayers[data.id].powerText.destroy();
      otherPlayers[data.id].usernameText.destroy();
      delete otherPlayers[data.id];
    }
  }
}

function preload() {
  this.load.image('playerSprite', '/game/static/assets/PurplePlanet.png');
  this.load.image('background', '/game/static/assets/Background.png');
  this.load.image('food', '/game/static/assets/sun.png');
}

function create() {
  // Set background to lowest depth
  const background = this.add.tileSprite(0, 0, worldWidth, worldHeight, 'background').setOrigin(0, 0);
  background.setDepth(0);

  this.physics.world.setBounds(0, 0, worldWidth, worldHeight);

  player = this.physics.add.sprite(worldWidth / 2, worldHeight / 2, 'playerSprite');
  player.setOrigin(0.5, 0.5);
  player.setScale(playerInitialSize);
  player.setCollideWorldBounds(true);
  player.setDepth(1);

  // Create power text for local player
  playerPowerText = this.add.text(0, 0, playerPower.toString(), {
    fontSize: '16px',
    color: '#ffffff',
    align: 'center',
    backgroundColor: '#000000',
    padding: { x: 8, y: 4 },
    stroke: '#000000',
    strokeThickness: 4
  });
  playerPowerText.setOrigin(0.5, 0.5);
  playerPowerText.setPosition(player.x, player.y);
  playerPowerText.setDepth(2);

  // Create timer text below power text
  timerText = this.add.text(0, 0, '5:00', {
    fontSize: '12px',
    color: '#ffffff',
    align: 'center',
    backgroundColor: '#000000',
    padding: { x: 8, y: 4 },
    stroke: '#000000',
    strokeThickness: 4
  });
  timerText.setOrigin(0.5, 0.5);
  timerText.setPosition(player.x, player.y + 30);
  timerText.setDepth(100);

  cursors = this.input.keyboard.addKeys('W,A,S,D');

  this.cameras.main.setBounds(0, 0, worldWidth, worldHeight);
  this.cameras.main.startFollow(player, true, 0.08, 0.08);
  
  // Create initial WebSocket connection
  socket = new WebSocket(`ws://${location.host}/ws/game`);
  setupSocketListeners();

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

  // Update local player's power text and timer position
  playerPowerText.setPosition(player.x, player.y);
  timerText.setPosition(player.x, player.y + 30);
}