// Get the game container's dimensions
const container = document.querySelector('.game-container');
const containerWidth = container.clientWidth;
const containerHeight = container.clientHeight;

const config = {
  type: Phaser.AUTO,
  width: containerWidth,
  height: containerHeight,
  backgroundColor: '#FF0000',  // Set the background color to red
  scene: {
    preload: preload,
    create: create,
    update: update
  }
};

const game = new Phaser.Game(config);

let player;
let target = null;
let blackDots = [];

function preload() {
  // Load any assets here if needed (e.g., images, sprites)
}

function create() {
  // Create blue circle in the center of the container
  player = this.add.circle(containerWidth / 2, containerHeight / 2, 15, 0x0000ff);
  player.setOrigin(0.5, 0.5); // Ensure the circle's origin is at its center

  // Create black dots
  for (let i = 0; i < 10; i++) {
    const x = Phaser.Math.Between(50, containerWidth - 50);
    const y = Phaser.Math.Between(50, containerHeight - 50);
    const dot = this.add.circle(x, y, 10, 0x000000);
    blackDots.push(dot);
  }

  // Set up input event to track mouse click
  this.input.on('pointerdown', pointer => {
    target = new Phaser.Math.Vector2(pointer.x, pointer.y);
  });
}

function update() {
  if (target) {
    // Calculate distance between player and target
    const distance = Phaser.Math.Distance.Between(player.x, player.y, target.x, target.y);
    const speed = 200; // Speed of the player (pixels per second)
    const dt = 1 / 60; // Time delta assuming 60fps

    if (distance > 1) {
      const angle = Phaser.Math.Angle.Between(player.x, player.y, target.x, target.y);
      player.x += Math.cos(angle) * speed * dt;
      player.y += Math.sin(angle) * speed * dt;
    }

    // Check if player touches any black dots
    blackDots = blackDots.filter(dot => {
      const d = Phaser.Math.Distance.Between(player.x, player.y, dot.x, dot.y);
      if (d < 15 + 10) { // If player touches a dot, destroy the dot
        dot.destroy();
        const x = Phaser.Math.Between(50, containerWidth - 50);
        const y = Phaser.Math.Between(50, containerHeight - 50);
        const dot2 = this.add.circle(x, y, 10, 0x000000);
        blackDots.push(dot2);
        return false;
      }
      return true;
    });
  }
}
