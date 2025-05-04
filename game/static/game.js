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

// --- New State Variables ---
let isInvulnerable = false;
let invulnerabilityEndTime = 0;
let invulnerabilityText = null; // Text object for invulnerability timer
let respawnMessageText = null; // Text object for "You got eaten!" message
let respawnEndTime = 0;     // Track when respawn message should disappear
let newGameTimerText = null;   // Text object for "New game starting..."
let newGameEndTime = 0;      // Track when new game timer should end
let isIntermission = false;    // Flag to hide invuln text during game end countdown
let playerVisible = true; // To handle hiding player when "eaten"
let playerInputDisabled = false; // To disable input when "eaten"
// --- End New State Variables ---

// --- Minimap Configuration ---
const MINIMAP_WIDTH = 200;
const MINIMAP_HEIGHT = 150;
const MINIMAP_X = 10;
const MINIMAP_Y = 10;
const MINIMAP_ZOOM = 0.05; // Zoom out more
const MINIMAP_BORDER_COLOR = 0xffffff; // White border
const MINIMAP_BORDER_THICKNESS = 2;
// --- End Minimap Configuration ---

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
        
        // Create the other player sprite with default texture initially
        const other = scene.add.sprite(info.x, info.y, 'playerSprite').setScale(otherScale);
        other.setDepth(1);
        
        // If the player has a username, fetch their custom skin
        if (info.username && info.username !== 'Guest') {
          fetch('/api/getImg', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({ message: info.username })
          })
          .then(response => response.json())
          .then(data => {
            if (data && data.fileName) {
              // Load the custom skin for this player
              const textureKey = `player_${id}_skin`;
              scene.textures.exists(textureKey) || scene.load.image(textureKey, `/pictures/${data.fileName}`);
              scene.load.once('complete', () => {
                // Update the sprite with the custom texture if it still exists
                if (otherPlayers[id] && otherPlayers[id].sprite) {
                  otherPlayers[id].sprite.setTexture(textureKey);
                }
              });
              scene.load.start();
            }
          })
          .catch(error => console.error(`Error loading skin for player ${id}:`, error));
        }

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
        const otherPlayer = otherPlayers[id];

        // --- Update Visibility/Appearance based on Server State --- 
        if (info.is_respawning) {
            // Hide if respawning
            if (otherPlayer.sprite.visible) otherPlayer.sprite.setVisible(false);
            if (otherPlayer.powerText.visible) otherPlayer.powerText.setVisible(false);
            if (otherPlayer.usernameText.visible) otherPlayer.usernameText.setVisible(false);
        } else {
            // Ensure visible if not respawning
            if (!otherPlayer.sprite.visible) otherPlayer.sprite.setVisible(true);
            if (!otherPlayer.powerText.visible) otherPlayer.powerText.setVisible(true);
            if (!otherPlayer.usernameText.visible) otherPlayer.usernameText.setVisible(true);

            // Apply invulnerability visual (e.g., transparency)
            if (info.isInvulnerable) {
                // Make more obvious: Tint yellow and slightly transparent
                otherPlayer.sprite.setAlpha(0.7);
                otherPlayer.sprite.setTint(0xffff00); // Yellow tint
            } else {
                otherPlayer.sprite.setAlpha(1.0); // Fully opaque
                otherPlayer.sprite.clearTint(); // Remove tint
            }
        }
        // --- End State-Based Visibility --- 

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
  } else if (data.type === "pre_reset_timer") {
    showNewGameTimer(data.duration);
    
    // Set intermission flag
    isIntermission = true;
  } else if (data.type === "game_over") {
    const scene = game.scene.scenes[0]; // Ensure scene is defined
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

    // Clear the "New game starting" timer text
    hideNewGameTimer();

    // Clear intermission flag
    isIntermission = false;
  } else if (data.type === "game_reset") {
    // Reset local player's power
    playerPower = 1;
    playerPowerText.setText('1');
    
    // Reset player position
    player.x = worldWidth / 2;
    player.y = worldHeight / 2;
    
    // Update timer with full duration
    const minutes = Math.floor(data.time_remaining / 60);
    const seconds = Math.floor(data.time_remaining % 60);
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

    hideNewGameTimer(); // Use helper to clear timer

    // Clear intermission flag
    isIntermission = false;

    // Ensure player sprite & UI are visible and positioned (visual reset)
    if(player) {
        player.x = worldWidth / 2; 
        player.y = worldHeight / 2;
        player.setVisible(true);
        playerVisible = true;
        playerInputDisabled = false; 
    }
    if (playerPowerText) playerPowerText.setVisible(true);
    if (timerText) timerText.setVisible(true);
    if (localUsernameText) localUsernameText.setVisible(true);

    // Start client-side visual invulnerability timer for the new round
    startInvulnerability(10);

  } else if (data.type === "remove") {
    if (otherPlayers[data.id]) {
      otherPlayers[data.id].sprite.destroy();
      if (otherPlayers[data.id].powerText) otherPlayers[data.id].powerText.destroy();
      if (otherPlayers[data.id].usernameText) otherPlayers[data.id].usernameText.destroy();
      delete otherPlayers[data.id];
    }
  } else if (data.type === "eaten") {
    // Player was eaten
    playerVisible = false;
    playerInputDisabled = true;
    
    const scene = game.scene.scenes[0];

    // Hide player and associated UI elements
    const deathX = player ? player.x : scene.cameras.main.scrollX + scene.cameras.main.width / 2;
    const deathY = player ? player.y : scene.cameras.main.scrollY + scene.cameras.main.height / 2;

    if (player) player.setVisible(false);
    if (playerPowerText) playerPowerText.setVisible(false);
    if (timerText) timerText.setVisible(false);
    if (localUsernameText) localUsernameText.setVisible(false);
    if (invulnerabilityText) invulnerabilityText.setVisible(false);
    if (player && player.body) player.body.setVelocity(0, 0);

    // Display "You got eaten!" message
    if (respawnMessageText) {
        respawnMessageText.destroy();
        respawnMessageText = null;
    }
    
    respawnMessageText = scene.add.text(deathX, deathY - 60,
      'You got eaten! Wait 10 seconds to respawn...', {
      fontSize: '24px', color: '#ff0000', align: 'center',
      padding: { x: 15, y: 10 }
    });

    if (respawnMessageText) {
        respawnMessageText.setOrigin(0.5);
        respawnMessageText.setDepth(500);
        respawnMessageText.setVisible(true);
    }

    // Start countdown timer
    respawnEndTime = scene.time.now + 10000;

    // Clear intermission flag
    isIntermission = false;
  } else if (data.type === "respawn") {
    // Player is respawning (message from server)
    console.log("Received 'respawn' message.");
    if (player) {
      player.setPosition(data.x, data.y);
      
      // Make player and UI visible again
      player.setVisible(true);
      if (playerPowerText) playerPowerText.setVisible(true);
      if (timerText) timerText.setVisible(true);
      if (localUsernameText) localUsernameText.setVisible(true);
      playerVisible = true;
      playerInputDisabled = false;
      startInvulnerability(10);
    }
    // Ensure power is reset visually (server handles the actual reset)
    playerPower = 1;
    if (playerPowerText) playerPowerText.setText(playerPower.toString());
  } else if (data.type === "achievement_unlocked") {
    // New achievement unlocked! Display notification.
    console.log("Achievement Unlocked:", data.achievement);
    displayAchievementNotification(scene, data.achievement.name, data.achievement.description);
  }
}

function preload() {
  // Fetch and load the player's custom skin
  this.load.image('background', '/game/static/assets/Background.png');
  this.load.image('food', '/game/static/assets/sun.png');
  
  // Default fallback sprite (will be used until custom image is loaded)
  this.load.image('playerSprite', '/game/static/assets/PurplePlanet.png');
  
  // Load the player's custom sprite if they have one
  const scene = this;
  fetch('/api/playerSprite')
    .then(response => response.json())
    .then(data => {
      if (data && data.fileName) {
        // Load the custom skin with a unique key
        scene.load.image('customPlayerSprite', `/pictures/${data.fileName}`);
        scene.load.once('complete', () => {
          // Once loaded, update all references to use the custom sprite
          if (player) {
            player.setTexture('customPlayerSprite');
          }
        });
        // Start the load
        scene.load.start();
      }
    })
    .catch(error => {
      console.error('Error loading custom player sprite:', error);
      // Will fallback to default sprite
    });
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
    // Spawn player in the middle of the world
    const playerTexture = scene.textures.exists('customPlayerSprite') ? 'customPlayerSprite' : 'playerSprite';
    player = scene.physics.add.sprite(worldWidth / 2, worldHeight / 2, playerTexture);
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
    scene.cameras.main.setName('main'); // Good practice to name cameras

    // --- Minimap Camera Setup ---
    const minimap = scene.cameras.add(MINIMAP_X, MINIMAP_Y, MINIMAP_WIDTH, MINIMAP_HEIGHT).setZoom(MINIMAP_ZOOM);
    minimap.setBounds(0, 0, worldWidth, worldHeight);
    minimap.startFollow(player, true, 0.08, 0.08);
    minimap.setBackgroundColor(0x000000); // Black background for minimap
    minimap.setName('minimap');

    // --- Minimap Border ---
    const minimapBorder = scene.add.graphics();
    minimapBorder.lineStyle(MINIMAP_BORDER_THICKNESS, MINIMAP_BORDER_COLOR, 1);
    minimapBorder.strokeRect(MINIMAP_X, MINIMAP_Y, MINIMAP_WIDTH, MINIMAP_HEIGHT);
    minimapBorder.setScrollFactor(0); // Keep border fixed on screen
    minimapBorder.setDepth(150); // Ensure border is above minimap but below main UI if needed

    // --- Ignore Fixed UI on Minimap ---
    // Make sure elements with scrollFactor(0) are not drawn by the minimap
    minimap.ignore([leaderboardText, minimapBorder]);
    // Note: Player-attached text (power, username, invuln) will correctly appear on both cameras
    // If respawnMessageText exists at creation, ignore it too (it's centered)
    if (respawnMessageText) {
      minimap.ignore(respawnMessageText);
      respawnMessageText.setScrollFactor(0); // Ensure it stays centered
    }

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

    // Start with invulnerability
    startInvulnerability(10); // 5 seconds invulnerability on initial spawn

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

// --- New Invulnerability Functions ---
function startInvulnerability(durationSeconds) {
  const scene = game.scene.scenes[0];
  if (!scene || !player || !player.body || !player.active) {
      return;
  }
  
  isInvulnerable = true;
  invulnerabilityEndTime = scene.time.now + durationSeconds * 1000;

  // Make player slightly transparent or add tint
  if (player) player.setAlpha(0.7); 

  // Create/update invulnerability timer text
  if (invulnerabilityText) invulnerabilityText.destroy();
  invulnerabilityText = scene.add.text(0, 0, `Invulnerable: ${durationSeconds.toFixed(1)}s`, {
    fontSize: '10px', color: '#00ff00', align: 'center',
    backgroundColor: 'rgba(0,0,0,0.5)', padding: { x: 5, y: 2 }
  });

  if (invulnerabilityText) {
      invulnerabilityText.setOrigin(0.5, 0.5);
      invulnerabilityText.setDepth(101); // Above player but below UI
      updateInvulnerabilityTextPosition(); // Initial positioning
      invulnerabilityText.setVisible(!isIntermission); // Hide if intermission
  }
}

function endInvulnerability() {
  isInvulnerable = false;
  invulnerabilityEndTime = 0;
  if (player) player.setAlpha(1.0); // Restore normal alpha

  if (invulnerabilityText) {
    invulnerabilityText.destroy();
    invulnerabilityText = null;
  }
}

function updateInvulnerabilityTextPosition() {
  if (invulnerabilityText && player) {
    // Position above username text
    invulnerabilityText.setPosition(player.x, player.y - 45); 
  }
}
// --- End Invulnerability Functions ---

// --- Achievement Notification Function ---
function displayAchievementNotification(scene, name, description) {
    if (!scene) return;
    console.log(`[AchievementNotify] Called with: name='${name}', desc='${description}'`);

    const notificationY = 50; // Position from the top
    const displayDuration = 5000; // 5 seconds
    const camera = scene.cameras.main;
    if (!camera) {
        console.error("[AchievementNotify] Could not get main camera!");
        return;
    }

    // Create a container for the notification text
    const notificationGroup = scene.add.group();

    // Background rectangle
    const bgRect = scene.add.graphics(); // Use graphics for flexible background
    bgRect.fillStyle(0x1a0f26, 0.85); // Dark semi-transparent purple
    bgRect.lineStyle(2, 0xffd700, 1); // Gold border
    // Dimensions will be set after text is created

    // Achievement Name Text
    const nameText = scene.add.text(0, 0, `🏆 ${name} 🏆`, { // Add trophy icons
        fontSize: '18px',
        color: '#ffd700', // Gold color
        align: 'center',
        fontStyle: 'bold'
    });
    nameText.setOrigin(0.5, 0);

    // Achievement Description Text
    const descText = scene.add.text(0, 0, description, {
        fontSize: '14px',
        color: '#ffffff',
        align: 'center',
        wordWrap: { width: 380 } // Wrap text
    });
    descText.setOrigin(0.5, 0);

    // Calculate background dimensions based on text
    const padding = 15;
    const totalTextHeight = nameText.height + 5 + descText.height; // Add spacing between lines
    const bgWidth = Math.max(nameText.width, descText.width) + padding * 2;
    const bgHeight = totalTextHeight + padding * 2;

    // Position texts relative to the center of the screen horizontally
    const centerX = camera.width / 2; // Use camera width
    nameText.setPosition(centerX, notificationY + padding);
    descText.setPosition(centerX, notificationY + padding + nameText.height + 5);

    // Draw the background rectangle behind the text
    bgRect.fillRoundedRect(centerX - bgWidth / 2, notificationY, bgWidth, bgHeight, 10);
    bgRect.strokeRoundedRect(centerX - bgWidth / 2, notificationY, bgWidth, bgHeight, 10);

    console.log(`[AchievementNotify] Created text/graphics. bgRect:`, bgRect, `nameText:`, nameText, `descText:`, descText);

    // Add elements to the group
    notificationGroup.add(bgRect);
    notificationGroup.add(nameText);
    notificationGroup.add(descText);

    // Make the group fixed to the camera
    notificationGroup.getChildren().forEach(child => {
        child.setScrollFactor(0);
        child.setDepth(1000); // Ensure it's on top
        console.log(`[AchievementNotify] Child properties:`, { x: child.x, y: child.y, alpha: child.alpha, depth: child.depth, visible: child.visible });
    });

    // Fade out and destroy after duration
    console.log('[AchievementNotify] Setting tween for fade out.');
    scene.tweens.add({
        targets: notificationGroup.getChildren(),
        alpha: 0,
        delay: displayDuration - 500, // Start fading 500ms before end
        duration: 500,
        onComplete: () => {
            notificationGroup.destroy(true); // Destroy group and children
        }
    });
}
// --- End Achievement Notification ---

// --- New Game Timer Text Helper Functions ---
function showNewGameTimer(duration) {
    const scene = game.scene.scenes[0];
    if (!scene) { // Player might not be needed if text is screen-relative
        return;
    }
    const cam = scene.cameras.main;
    if (!cam) {
        return;
    }

    hideNewGameTimer(); // Ensure any previous timer is gone

    // Position relative to camera viewport center
    const textX = cam.scrollX + cam.width / 2;
    const textY = cam.scrollY + cam.height / 2;

    newGameTimerText = scene.add.text(textX, textY,
        `New game starting in ${duration} seconds!`, {
        fontSize: '28px', // Make size consistent 
        color: '#FFD700', // Darker Yellow / Gold
        align: 'center',
        backgroundColor: 'rgba(0,0,0,0.6)', 
        padding: { x: 20, y: 15 } // Adjust padding
    });

    newGameTimerText.setOrigin(0.5);
    newGameTimerText.setScrollFactor(0); // <<< Keep fixed on screen
    newGameTimerText.setDepth(550); // Ensure it's above other UI
    newGameTimerText.setVisible(true);

    newGameEndTime = scene.time.now + duration * 1000;
}

function hideNewGameTimer() {
    if (newGameTimerText) {
        newGameTimerText.destroy();
        newGameTimerText = null;
    }
    newGameEndTime = 0; // Always reset end time
}
// --- End Helper Functions ---

// Function to reset player speed after debuff duration
function resetSlowness() {
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
  if (!player || !cursors || !player.body || !player.active) {
    return; // Don't run update logic if game setup hasn't completed or player inactive
  }

  // --- Player Movement Input (Only if not disabled) ---
  if (!playerInputDisabled) {
    const dt = delta / 1000;
    let moveX = 0;
    let moveY = 0;

    if (cursors.A.isDown) moveX = -1;
    else if (cursors.D.isDown) moveX = 1;
    if (cursors.W.isDown) moveY = -1;
    else if (cursors.S.isDown) moveY = 1;

    const moveVector = new Phaser.Math.Vector2(moveX, moveY).normalize();

    player.body.setVelocity(moveVector.x * playerSpeed, moveVector.y * playerSpeed);
  } else {
    // Ensure player velocity is zeroed out if input is disabled
    player.body.setVelocity(0, 0);
  }
  // --- End Player Movement Input ---

  // --- Moved from handleSocketMessage --- 
  // Update New Game Timer text if active
  if (newGameTimerText && newGameTimerText.active && newGameEndTime > 0) {
    // Text position is now fixed via scrollFactor(0) in showNewGameTimer
  } else if (newGameTimerText) {
    // If text object exists but shouldn't (e.g., endTime <= 0), ensure it's hidden/removed
    newGameTimerText.destroy();
    newGameTimerText = null;
  }

  // --- Invulnerability Update Logic (Uses 'time') ---
  if (isInvulnerable) {
    const remainingTime = (invulnerabilityEndTime - time) / 1000;
    if (remainingTime > 0 && !isIntermission) {
      if (invulnerabilityText) {
        invulnerabilityText.setText(`Invulnerable: ${remainingTime.toFixed(1)}s`);
        updateInvulnerabilityTextPosition(); // Keep text positioned correctly
        if (!invulnerabilityText.visible) invulnerabilityText.setVisible(true); // Ensure visible
      }
      // Optional: Add visual effect like blinking
      player.setAlpha(0.5 + Math.abs(Math.sin(time / 150)) * 0.4); // Simple blink effect
    } else { // Time ended OR isIntermission is true
      // Hide invulnerability text if it exists
      if (invulnerabilityText && invulnerabilityText.visible) {
          invulnerabilityText.setVisible(false);
      }
      // End invulnerability state if time is up
      if (remainingTime <= 0) {
        endInvulnerability();
      }
    }
  }
  // --- End Invulnerability Update Logic ---

  // --- Respawn Countdown Message Update (Uses 'time') ---
  if (respawnMessageText && respawnEndTime > 0) {
    const scene = game.scene.scenes[0]; // Ensure scene is available

    // Note: Text position is fixed at death location (not updated here)

    // Update countdown text
    const remainingSeconds = Math.max(0, Math.ceil((respawnEndTime - time) / 1000));
    respawnMessageText.setText(`You've been eaten! Respawning in ${remainingSeconds} seconds`);

    // Fallback removal if time expires before respawn message arrives from server
    if (time >= respawnEndTime) {
        respawnMessageText.destroy();
        respawnMessageText = null;
        respawnEndTime = 0;
    }
  }
  // --- End Respawn Countdown ---

  // Ensure player visibility matches state
  if (player && player.visible !== playerVisible) {
      player.setVisible(playerVisible);
  }

  // Update local player's power text and timer position
  playerPowerText.setPosition(player.x, player.y);
  timerText.setPosition(player.x, player.y + 30);
  // Update local username text position
  if (localUsernameText) {
    localUsernameText.setPosition(player.x, player.y - 30);
  }
}