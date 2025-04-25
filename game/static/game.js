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
let localUsernameText;
let leaderboardText;
let foodInstances = {};  // Store food sprites

// Function to setup WebSocket listeners
function setupSocketListeners() {
  socket.addEventListener("open", () => {
    console.log("Connected to server");
  });

  socket.addEventListener("close", (event) => {
    console.log("Disconnected from server. Code:", event.code, "Reason:", event.reason);
    if (event.code === 1008 && event.reason === "User already connected") {
      console.error("Attempted to connect again while already connected.");
      if (scene.input) scene.input.enabled = false; 
    } else if (!event.wasClean) {
        console.warn("Lost connection to the server.");
        if (scene.input) scene.input.enabled = false;
    }
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

  // Handle error messages from server (e.g., already connected)
  if (data.type === "error") {
    console.error("Server error message received:", data.message);
    if (scene && scene.input) scene.input.enabled = false;
    return; // Stop processing this message further
  }

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

    // --- Leaderboard Update --- 
    const allPlayers = [];
    // Add local player
    allPlayers.push({ 
        username: localUsernameText ? localUsernameText.text : 'Me', // Use current username text or default
        power: playerPower 
    });
    // Add other players
    for (const id in otherPlayers) {
        allPlayers.push({ 
            username: otherPlayers[id].usernameText.text,
            power: otherPlayers[id].power
        });
    }

    // Sort players by power (descending)
    allPlayers.sort((a, b) => b.power - a.power);

    // Get top 10 players
    const topPlayers = allPlayers.slice(0, 10);

    // Format leaderboard string
    let leaderboardString = "Leaderboard:\n";
    topPlayers.forEach((p, index) => {
        leaderboardString += `${index + 1}. ${p.username}: ${p.power}\n`;
    });

    // Update leaderboard text object
    if (leaderboardText) {
        leaderboardText.setText(leaderboardString);
    }
    // --- End Leaderboard Update ---

    for (const [id, info] of Object.entries(data.players)) {
      if (id === socket.id) {
        // Update local player's power
        playerPower = info.power;
        playerPowerText.setText(playerPower.toString());
        // Update local player scale based on power
        const localScale = playerInitialSize + playerPower * 0.005; // Adjust scaling factor as needed
        player.setScale(localScale);
        // Update local username text
        if (localUsernameText) {
          localUsernameText.setText(info.username || 'Me'); 
        }
        continue;
      }

      if (!otherPlayers[id]) {
        const otherScale = playerInitialSize + info.power * 0.005; // Scale based on power
        const other = scene.add.sprite(info.x, info.y, 'playerSprite').setScale(otherScale);
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
        // Scale other player based on power
        const otherScale = playerInitialSize + info.power * 0.005; // Adjust scaling factor as needed
        otherPlayers[id].sprite.setScale(otherScale);

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

  // --- WebSocket Connection First ---
  const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
  socket = new WebSocket(`${protocol}${location.host}/ws/game`);
  
  // Store 'this' context for use inside listeners
  const scene = this; 

  socket.addEventListener("open", () => {
    console.log("Connected to server, initializing game...");

    // --- Initialize Game Elements AFTER successful connection ---
    player = scene.physics.add.sprite(worldWidth / 2, worldHeight / 2, 'playerSprite');
    player.setOrigin(0.5, 0.5);
    player.setScale(playerInitialSize);
    player.setCollideWorldBounds(true);
    player.setDepth(1);

    // Create power text for local player
    playerPowerText = scene.add.text(0, 0, playerPower.toString(), {
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
    timerText = scene.add.text(0, 0, '5:00', {
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

    // Create username text for local player above the player
    localUsernameText = scene.add.text(0, 0, 'Me', { // Initial placeholder
      fontSize: '8px',
      color: '#ffffff',
      align: 'center',
      backgroundColor: '#000000',
      padding: { x: 8, y: 4 },
      stroke: '#000000',
      strokeThickness: 4
    });
    localUsernameText.setOrigin(0.5, 0.5);
    localUsernameText.setPosition(player.x, player.y - 30); // Position above player
    localUsernameText.setDepth(2);

    // Create Leaderboard Text (Top Right Corner)
    leaderboardText = scene.add.text(containerWidth - 10, 10, 'Leaderboard:', {
      fontSize: '12px',
      color: '#ffffff',
      align: 'right', // Align text to the right
      backgroundColor: 'rgba(0, 0, 0, 0.5)', // Semi-transparent background
      padding: { x: 10, y: 5 }
    });
    leaderboardText.setOrigin(1, 0); // Anchor to top-right
    leaderboardText.setScrollFactor(0); // Keep it fixed on screen
    leaderboardText.setDepth(100); // Ensure it's above other elements

    cursors = scene.input.keyboard.addKeys('W,A,S,D');

    scene.cameras.main.setBounds(0, 0, worldWidth, worldHeight);
    scene.cameras.main.startFollow(player, true, 0.08, 0.08);

    // Start sending position updates
    scene.time.addEvent({
      delay: 50,
      loop: true,
      callback: () => {
        if (socket.readyState === WebSocket.OPEN && player) { // Check if player exists
          socket.send(JSON.stringify({
            x: player.x,
            y: player.y
          }));
        }
      }
    });
    // --- End Game Initialization ---

  });

  socket.addEventListener("close", (event) => {
    console.log("Disconnected from server. Code:", event.code, "Reason:", event.reason);
    if (event.code === 1008 && event.reason === "User already connected") {
      console.error("Attempted to connect again while already connected.");
      if (scene.input) scene.input.enabled = false; 
    } else if (!event.wasClean) {
        console.warn("Lost connection to the server.");
        if (scene.input) scene.input.enabled = false;
    }
  });

  socket.addEventListener("error", (error) => {
    console.error("WebSocket error:", error);
  });

  // Setup message listener immediately
  socket.addEventListener("message", handleSocketMessage); 

}

// Function to reset player speed after debuff duration
function resetSlowness() {
    console.log("Debuff expired, resetting slowness."); // Debug log
    slownessFactor = 1.0;
    debuffTimer = null; // Clear the timer reference

    // Destroy debuff indicator
    if (debuffIndicator) {
        debuffIndicator.destroy();
        debuffIndicator = null;
    }
}

function update(time, delta) {
  // Check if player and cursors are initialized before using them
  if (!player || !cursors || !player.body) {
    return; // Don't run update logic if game setup hasn't completed
  }

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
  // Update local username text position
  if (localUsernameText) {
    localUsernameText.setPosition(player.x, player.y - 30);
  }
}