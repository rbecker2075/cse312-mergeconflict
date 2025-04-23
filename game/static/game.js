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
  width: containerWidth, // Keep viewport size based on container
  height: containerHeight,
  physics: { // Add Arcade Physics
    default: 'arcade',
    arcade: {
      // gravity: { y: 200 } // Optional gravity
      debug: false // Set to true for collision debugging visuals
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
let player2 = null; // Second player piece after split
let cursors;
let keySPACE;
let canSplit = true;
let mergeTimer = null;
const playerSpeed = 200;
// Increase boost significantly again
const playerSplitBoost = 2500; // Speed boost on split (applied as velocity)
const playerInitialSize = 0.15; // Initial scale factor for the sprite
const playerSplitFollowSpeed = 100;

const foodSize = 0.05; // Scale factor for the food sprite
const foodRadius = 10; // Approximate radius for collision (adjust based on sun.png actual size and scale)
const growthFactor = 0.0085; // How much scale increases per food item (Increased from 0.005)
const targetFoodCount = 150; // Target number of food items in the world

// --- Buff Constants ---
const buffSize = 0.08; // Scale factor for the buff sprite
const buffMultiplier = 1.5; // Speed increase factor (75% increase)
const buffDuration = 4000; // Milliseconds the speed boost lasts
const targetBuffCount = 50; // Target number of buffs in the world
let speedMultiplier = 1.0; // Current speed multiplier
let speedBoostTimer = null; // Timer for the buff duration
let buffIndicator = null; // Sprite to show buff is active
const buffIndicatorScale = 0.04; // Scale for the indicator icon
const buffIndicatorOffsetY = 3; // Vertical offset above player

// Let foods be a physics group
let foods;
// Let buffs be a physics group
let buffs;

function preload() {
  // Load the player sprite
  this.load.image('playerSprite', '/game/static/assets/PurplePlanet.png');
  // Load background and food images
  this.load.image('background', '/game/static/assets/Background.png');
  this.load.image('food', '/game/static/assets/sun.png');
  // Load the buff image
  this.load.image('buff', '/game/static/assets/rocket.png');
}

function create() {
  // Add tiled background
  this.add.tileSprite(0, 0, worldWidth, worldHeight, 'background').setOrigin(0, 0);

  // Set world bounds
  this.physics.world.setBounds(0, 0, worldWidth, worldHeight);

  // Create player sprite with physics
  // Spawn player in the center of the world
  player = this.physics.add.sprite(worldWidth / 2, worldHeight / 2, 'playerSprite');
  player.setOrigin(0.5, 0.5);
  player.setScale(playerInitialSize);
  player.setCollideWorldBounds(true); // Keep player inside world
  player.setDepth(1); // Ensure player is above background, below indicator
  // player.body.setBounce(0.2); // Optional bounce
  // player.body = { velocity: new Phaser.Math.Vector2(0, 0) }; // Remove old velocity object

  // Create food group
  foods = this.physics.add.group();

  // Create initial food items spread across the world
  for (let i = 0; i < targetFoodCount; i++) { // Spawn initial food up to the target count
    spawnFood(this);
  }

  // Create buff group
  buffs = this.physics.add.group();
  // Spawn initial buffs up to the target count
  for (let i = 0; i < targetBuffCount; i++) {
      spawnBuff(this);
  }

  // Set up keyboard input
  cursors = this.input.keyboard.addKeys('W,A,S,D');
  keySPACE = this.input.keyboard.addKey(Phaser.Input.Keyboard.KeyCodes.SPACE);

  // --- Camera Setup ---
  this.cameras.main.setBounds(0, 0, worldWidth, worldHeight);
  this.cameras.main.startFollow(player, true, 0.08, 0.08); // Smooth follow
  // this.cameras.main.setZoom(1); // Optional initial zoom

  // --- Physics Overlaps ---
  // Check overlap between player and food group
  this.physics.add.overlap(player, foods, collectFood, null, this);
  // Check overlap between player and buff group
  this.physics.add.overlap(player, buffs, collectBuff, null, this);

  // Player 2 overlap will be added dynamically when created
}

// Function to spawn a single food item
function spawnFood(sceneContext) {
  const x = Phaser.Math.Between(50, worldWidth - 50); // Use world bounds
  const y = Phaser.Math.Between(50, worldHeight - 50);
  const foodItem = foods.create(x, y, 'food'); // Add directly to the physics group
  foodItem.setScale(foodSize);
  foodItem.setOrigin(0.5, 0.5);
  // foodItem.setCircle(foodRadius); // Optional: Set circular physics body if needed
  foodItem.setImmovable(true); // Food doesn't get pushed
  foodItem.body.allowGravity = false; // Food doesn't fall
}

// Function to spawn a single buff item
function spawnBuff(sceneContext) {
  // Always try to spawn, density is handled in update
  const x = Phaser.Math.Between(100, worldWidth - 100); // Use world bounds, slightly inset
  const y = Phaser.Math.Between(100, worldHeight - 100);
  const buffItem = buffs.create(x, y, 'buff'); // Add directly to the physics group
  buffItem.setScale(buffSize);
  buffItem.setOrigin(0.5, 0.5);
  buffItem.setImmovable(true); // Buff doesn't get pushed
  buffItem.body.allowGravity = false; // Buff doesn't fall
  console.log("Buff spawned at:", x, y); // Debug log
}

// Callback function when player overlaps with food
function collectFood(playerPiece, foodItem) {
  // Increase player piece size
  playerPiece.scaleX += growthFactor;
  playerPiece.scaleY += growthFactor;
  // Optional: Update physics body size if needed after scaling
  // playerPiece.body.setSize(playerPiece.width * playerPiece.scaleX, playerPiece.height * playerPiece.scaleY);
  // playerPiece.body.offset.set(...) // Adjust offset if origin is not center

  // Remove the food item
  foodItem.destroy(); // Destroy the sprite and its physics body

  // Respawn a new food item somewhere else
  spawnFood(this);
}

// Callback function when player overlaps with a buff
function collectBuff(playerPiece, buffItem) {
  console.log("Buff collected!"); // Debug log
  // Destroy the buff item
  buffItem.destroy();

  // Apply speed boost
  speedMultiplier = buffMultiplier;

  // --- Create/Update Buff Indicator --- 
  // Destroy existing indicator first if player grabs another buff quickly
  if (buffIndicator) {
      buffIndicator.destroy();
  }
  // Use playerPiece's scene context to add the sprite
  const scene = playerPiece.scene;
  buffIndicator = scene.add.sprite(playerPiece.x, playerPiece.y, 'buff');
  buffIndicator.setScale(buffIndicatorScale);
  buffIndicator.setOrigin(0.5, 0.5);
  buffIndicator.setDepth(playerPiece.depth + 1); // Render above the player piece that collected it
  // Initial position update
  buffIndicator.y = playerPiece.y - (playerPiece.displayHeight / 2) - (buffIndicator.displayHeight / 2) - buffIndicatorOffsetY;

  // Clear any existing timer before starting a new one
  if (speedBoostTimer) {
    speedBoostTimer.remove(false); // Remove timer without calling its callback
  }

  // Set timer to reset speed
  speedBoostTimer = this.time.delayedCall(buffDuration, resetSpeed, [], this);

  // Respawn is handled by the density check in update now
}

// Function to reset player speed after buff duration
function resetSpeed() {
    console.log("Buff expired, resetting speed."); // Debug log
    speedMultiplier = 1.0;
    speedBoostTimer = null; // Clear the timer reference

    // Destroy buff indicator
    if (buffIndicator) {
        buffIndicator.destroy();
        buffIndicator = null;
    }
}

function update(time, delta) {
  const dt = delta / 1000; // Convert delta time to seconds

  // --- Player Movement ---
  let moveX = 0;
  let moveY = 0;

  if (cursors.A.isDown) {
    moveX = -1;
  } else if (cursors.D.isDown) {
    moveX = 1;
  }
  if (cursors.W.isDown) {
    moveY = -1;
  } else if (cursors.S.isDown) {
    moveY = 1;
  }

  // Normalize movement vector and set physics velocity using speed multiplier
  const moveVector = new Phaser.Math.Vector2(moveX, moveY).normalize();
  const effectiveSpeed = playerSpeed * speedMultiplier;
  player.body.setVelocity(moveVector.x * effectiveSpeed, moveVector.y * effectiveSpeed);

  // --- Splitting Mechanic ---
  if (keySPACE.isDown && canSplit && player2 === null) {
    canSplit = false; // Prevent actions until merge/animation complete

    const currentScale = player.scaleX;
    // --- Calculate scaled values ---
    const currentWidth = player.width * currentScale; // Player width before split
    const scaledTweenDistance = currentWidth * 0.5; // Push apart by half the original width
    const scaledSplitBoost = playerSplitBoost * (1 + currentScale * 0.1); // Slightly increase boost when bigger

    const splitScale = Math.sqrt((currentScale * currentScale) / 2);
    const launchDirection = player.body.velocity.length() > 0 ? player.body.velocity.clone().normalize() : new Phaser.Math.Vector2(1, 0);

    // Store current velocities before tween potentially stops them
    const currentVelX = player.body.velocity.x;
    const currentVelY = player.body.velocity.y;

    // Stop player briefly for the visual split animation
    player.body.setVelocity(0, 0);

    // Create player2 as a physics sprite
    player2 = this.physics.add.sprite(player.x, player.y, 'playerSprite'); // Start at same spot
    player2.setOrigin(0.5, 0.5);
    player2.setScale(splitScale);
    player2.setCollideWorldBounds(true);
    player2.body.setVelocity(0, 0); // Also start stationary for tween
    player2.setDepth(player.depth); // Ensure player2 is at the same depth as player1

    // Set player 1 scale
    player.setScale(splitScale);

    // Short tween for visual separation using scaled distance
    // const tweenDistance = 30; // How far they push apart visually - OLD Fixed Value
    const tweenDuration = 100; // Milliseconds for the visual split

    this.tweens.add({
        targets: player,
        x: player.x + launchDirection.x * scaledTweenDistance, // Use scaled distance
        y: player.y + launchDirection.y * scaledTweenDistance, // Use scaled distance
        duration: tweenDuration,
        ease: 'Linear' // or 'Power1'
    });

    this.tweens.add({
        targets: player2,
        x: player2.x - launchDirection.x * scaledTweenDistance, // Use scaled distance
        y: player2.y - launchDirection.y * scaledTweenDistance, // Use scaled distance
        duration: tweenDuration,
        ease: 'Linear',
        onComplete: () => {
            // --- Actions after visual split animation ---

            // Apply the main launch velocity to player 1 using scaled boost
            const launchVelocityX = currentVelX + launchDirection.x * scaledSplitBoost; // Use scaled boost
            const launchVelocityY = currentVelY + launchDirection.y * scaledSplitBoost; // Use scaled boost
            if (player && player.body) { // Check if player still exists
                 player.body.setVelocity(launchVelocityX, launchVelocityY);
            }

            // Add overlap check for player 2 (only if it exists)
            if (player2) {
                 this.physics.add.overlap(player2, foods, collectFood, null, this);
                 // Add overlap check for player 2 and buffs
                 this.physics.add.overlap(player2, buffs, collectBuff, null, this);
            }

            // Set timer to merge back (only if player2 was successfully created)
            if (player2) {
                mergeTimer = this.time.delayedCall(10000, mergePlayers, [], this);
            }
             // Note: canSplit remains false until mergePlayers is called
        }
    });

    // Moved timer and overlap setup into tween onComplete
    // player.body.setVelocity(launchVelocityX, launchVelocityY); // Removed from here
    // this.physics.add.overlap(player2, foods, collectFood, null, this); // Removed from here
    // mergeTimer = this.time.delayedCall(10000, mergePlayers, [], this); // Removed from here
  }

  // --- Player 2 Follow Logic ---
  if (player2) {
    // Use physics accelerateToObject for smoother following
    this.physics.accelerateToObject(player2, player, playerSplitFollowSpeed, 300, 300); // Adjust acceleration/max speed
  }

  // --- Maintain Food Density ---
  // Check periodically and spawn if below target
  if (foods.countActive(true) < targetFoodCount && Phaser.Math.RND.frac() < 0.1) { // Check 10% of frames
      spawnFood(this);
  }

  // --- Maintain Buff Density ---
  // Check periodically and spawn if below target
  if (buffs.countActive(true) < targetBuffCount && Phaser.Math.RND.frac() < 0.05) { // Check 5% of frames
      spawnBuff(this);
  }

  // --- Update Buff Indicator Position --- 
  if (buffIndicator && player) { // Check if indicator and player exist
      buffIndicator.x = player.x;
      // Adjust Y based on player's current display height
      buffIndicator.y = player.y - (player.displayHeight / 2) - (buffIndicator.displayHeight / 2) - buffIndicatorOffsetY;
  }

  // --- Collision Detection & Growth (Handled by physics overlaps now) ---
  /*
  const playerRadius = (player.width * player.scaleX) / 2; // Recalculate radius based on current scale
  // ... Old manual collision code removed ...
  */

   // --- Keep player within bounds (Handled by physics `setCollideWorldBounds` now) ---
   /*
   // ... Old manual boundary checks removed ...
   */
}

function mergePlayers() {
    if (player2) {
        const scale1Sq = player.scaleX * player.scaleX;
        const scale2Sq = player2.scaleX * player2.scaleX;
        const combinedScale = Math.sqrt(scale1Sq + scale2Sq);

        // Reset player 1's velocity before scaling to avoid physics glitches
        if (player && player.body) {
            player.body.setVelocity(0, 0);
        }

        player.setScale(combinedScale);
        // Optional: Update physics body size after merge
        // player.body.setSize(player.width * player.scaleX, player.height * player.scaleY);

        player2.destroy(); // Destroys sprite and physics body
        player2 = null;
    }

    // Ensure player depth is maintained after potential changes
    if (player) {
        player.setDepth(1);
    }

    canSplit = true;
    mergeTimer = null;
}

// Comments updated/removed
