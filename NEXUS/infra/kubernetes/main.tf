# Namespace para NEXUS
resource "kubernetes_namespace" "nexus" {
  metadata {
    name = "nexus"
    labels = {
      environment = "production"
      application = "nexus"
    }
  }
}

# ConfigMap para configuración de la aplicación
resource "kubernetes_config_map" "nexus_config" {
  metadata {
    name      = "nexus-config"
    namespace = kubernetes_namespace.nexus.metadata[0].name
  }

  data = {
    "app-config.yaml" = templatefile("${path.module}/templates/app-config.yaml.tpl", {
      database_url      = aws_db_instance.nexus_postgres.endpoint
      redis_url         = "redis://${module.redis.endpoint}:6379"
      weaviate_url      = "http://weaviate.nexus.svc.cluster.local:8080"
      blockchain_nodes  = join(",", [for i in range(7) : "node${i}.nexus.svc.cluster.local:9944"])
      openai_api_key    = var.openai_api_key
      environment       = "production"
    })
  }
}

# Secrets para información sensible
resource "kubernetes_secret" "nexus_secrets" {
  metadata {
    name      = "nexus-secrets"
    namespace = kubernetes_namespace.nexus.metadata[0].name
  }

  data = {
    "database-password"   = aws_db_instance.nexus_postgres.password
    "redis-password"      = module.redis.auth_token
    "openai-api-key"      = var.openai_api_key
    "jwt-secret"          = random_password.jwt_secret.result
    "encryption-key"      = random_password.encryption_key.result
  }

  depends_on = [kubernetes_namespace.nexus]
}

# ServiceAccount para el despliegue
resource "kubernetes_service_account" "nexus" {
  metadata {
    name      = "nexus-service-account"
    namespace = kubernetes_namespace.nexus.metadata[0].name
    annotations = {
      "eks.amazonaws.com/role-arn" = aws_iam_role.nexus.arn
    }
  }
}

# IAM Role para acceso a AWS resources
resource "aws_iam_role" "nexus" {
  name = "nexus-production-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "eks.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "nexus_s3" {
  role       = aws_iam_role.nexus.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_iam_role_policy_attachment" "nexus_rds" {
  role       = aws_iam_role.nexus.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonRDSFullAccess"
}